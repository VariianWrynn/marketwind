from enum import IntEnum


class SourceTier(IntEnum):
    EXCLUDED = 0
    SECONDARY = 1
    TRUSTED = 2
    DESIGNATED = 3
    OFFICIAL = 4


_OFFICIAL = frozenset({"cninfo.com.cn", "sse.com.cn", "szse.cn", "csrc.gov.cn", "pbc.gov.cn", "miit.gov.cn", "nfra.gov.cn"})
_DESIGNATED = frozenset({"cs.com.cn", "cnstock.com", "stcn.com", "zqrb.cn", "financialnews.com.cn", "jjckb.cn", "chinadaily.com.cn"})
_TRUSTED = frozenset({"finance.sina.com.cn", "yicai.com", "cls.cn", "caixin.com"})
_SECONDARY = frozenset({"news.cn", "xinhuanet.com", "people.com.cn", "21jingji.com", "jiemian.com", "finance.eastmoney.com", "data.eastmoney.com", "zhitongcaijing.com", "wallstreetcn.com", "thepaper.cn", "cnfin.com"})
_DENYLIST = frozenset({"caifuhao.eastmoney.com", "guba.eastmoney.com", "mguba.eastmoney.com", "quote.eastmoney.com", "emwap.eastmoney.com", "q.stock.sohu.com", "k.sina.com.cn", "k.sina.cn", "cj.sina.com.cn", "vip.stock.finance.sina.com.cn", "money.finance.sina.com.cn", "xueqiu.com", "tgb.cn"})


def classify(domain: str) -> SourceTier:
    # Denylist wins over all allowlists — exact match only (subdomains of deny entries are NOT blocked)
    if domain in _DENYLIST:
        return SourceTier.EXCLUDED

    for tier, allowlist in (
        (SourceTier.OFFICIAL, _OFFICIAL),
        (SourceTier.DESIGNATED, _DESIGNATED),
        (SourceTier.TRUSTED, _TRUSTED),
        (SourceTier.SECONDARY, _SECONDARY),
    ):
        for entry in allowlist:
            if domain == entry or domain.endswith("." + entry):
                return tier

    return SourceTier.EXCLUDED


def clears_law3(domain: str, source_is_primary: bool, attached_primary_url: str | None) -> bool:
    return attached_primary_url is not None or source_is_primary or classify(domain) >= SourceTier.TRUSTED


def is_officially_verified(domain: str, source_is_primary: bool, attached_primary_url: str | None) -> bool:
    return attached_primary_url is not None or source_is_primary or classify(domain) >= SourceTier.DESIGNATED
