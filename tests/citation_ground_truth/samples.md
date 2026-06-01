# Citation Ground Truth — 样本集

> **Read when:** 实现/修改 Verifier 或 Writer、或改动契约时读，作为 RED 回归基线。（本文件为输出层内容，保持中文。）

**用途**: Verifier / Writer 的 RED 测试基线。任何 Writer/Verifier/契约改动必须先过本集。
**构成**: 7 条真实（来自 2026-05-28 科创50 盘前 quote 池）+ 5 条合成（人为注入单一错误）。
**关键**: 标 `v0.2-gap` 的样本是当时契约抓不住的，已驱动 v0.3 修订。它们既测 Verifier，也证明契约缺了哪条规则。

事实仅作核验锚点，均可经各 URL 核对；本文件不复制原文，只标注注入的错误与期望判定。

---

## 真实样本（5/28 quote 池）

| ID | 来源 item | 陷阱类型 | 期望 ground truth | 抓它的层 | 契约状态 |
|---|---|---|---|---|---|
| **GT-R1** | item 9 大基金三期 70% 投设备材料 | 伪双源（两条 URL 同为 finance.sina.com.cn，仅 doc id 不同） | `corroboration_count = 1`，不可作双源 corroborate | I2（domain AND 规则） | ✅ v0.2 抓住 |
| **GT-R2** | item 4 长鑫"日赚 3.6 亿 vs 3.17 亿" | 派生指标口径分歧（分母用净利 vs 归母净利） | `derived_metric` claim，必须带 `methodology` 或只写 base figure（营收508/净利330.12/归母247.62） | I12 | `v0.2-gap` → v0.3 闭合（D-12） |
| **GT-R3** | item 5 美光万亿日期 | 跨日自我更正（昨日报告写 5/27，今日精确源确认 5/26） | 检测与昨日已发布 claim 冲突 → 生成 `correction` claim | I11 | `v0.2-gap` → v0.3 闭合（D-14） |
| **GT-R4** | item 1 + item 6 | 时间窗假矛盾（隔夜半导体领跌 vs 周二费半涨6%，不同交易日） | **不算矛盾**：time_window 不同（overnight_us 不同日） | I10 / RF-7 time-window-aware | `v0.2-gap`（假阳性）→ v0.3 闭合（D-13） |
| **GT-R5** | item 3 长鑫过会 | 真双源核心事件（STCN + Yicai，正样本） | 内容通过，但**全是媒体源、primary=0** → Gate 0 fail | Gate 0（缺 primary） | ✅ 正确拦截（暴露 Gap 1：Scout 需 primary-fetch） |
| **GT-R6** | item 8 半导体减持潮 145 亿 | 单源派生聚合（单 Sina 源 + "按 5/27 收盘价计算"的合计） | RF-6（单源量化）+ derived_metric 双重命中 | RF-6 + I12 | ✅ v0.3 抓住 |
| **GT-R7** | item 10 资金虹吸担忧 | 无归属市场情绪 | RF-4 reject（已接受代价，信号丢失） | RF-4 / Law 4 | ✅ 拒绝（attributed_sentiment 为 v0.3+ stub，D-15） |

---

## 合成样本（人为注入）

每条注入**单一**明确错误，ground truth 确定。

### GT-S1 · 纯数字错位（Misattribution）
- 素材：中芯国际 Q1'26（营收176.17亿/归母13.61亿，ithome）；海光信息 Q1'26（营收40.34亿/归母6.87亿，stcn）
- 注入：两家营收/归母数字**整体互换**
- 期望：先撞 **I3**（媒体源、primary=0）；纯数字归属错位由 **B4 judge** 语义不对应抓
- 标注须写明双重命中。⚠️ 纯测 judge 需 primary 版本（项目主人已决定暂不补，故本条主测 I3 路径，judge 层回归留待后补 primary 版）

### GT-S2 · 纯时态错误（Period mislabel）
- 素材：中芯国际 Q1'26 一季报（nbd），明确"第一季度"+"同比"
- 注入：Q1→Q2、同比→环比；数字真实
- 期望：规则层（数字字符串匹配）**会放行**；只有 **B4 judge** 理解财季/基期语义能抓
- 价值：本条是"纯规则层不够"的活证据。同样需 primary 版纯测 judge（暂缓）

### GT-S3a · Quoted inference（合法对照）
- 素材：中信证券硅片研报（stcn 转载），原文自带"涨价逻辑有望 2026 Q2 出现、看好中国硅片"结论
- 写法：带 attribution 引用该结论
- 期望：**通过**，category = `quoted_inference`

### GT-S3b · Model-stitched inference（违规）
- 素材：长鑫过会（stcn）+ 大基金三期 3440 亿（sina），两条独立事实
- 注入：拼成"国产半导体设备国产替代正在加速"——两源都没说过的结论
- 期望：**Law 4 违规**（model inference）
- ⚠️ **清洗说明**：原始注入版含"2026 Q2 进入加速涨价期"，该时点是从 S3a 研报飘来的第二层杂质，会给 judge 一条 span-回填捷径绕过因果检测。**定稿版去掉时点**，改为纯因果拼接"正在加速"，干净测 model inference

### GT-S4 · 过时事实（Stale fact）
- 素材：旧报道朱一明持兆易 7.90%（nbd 4/7）；新报道减持后降至 7.00%（sina 5/27 上交所披露）
- 注入：5/28 晨报用"目前合计持股 7.90%"引用旧报道
- 期望：引用真实、quote 对应，但"目前"把旧状态当现状
- 契约状态：`v0.2-gap`——旧 I6 只覆盖"主体属性"，持股比例是滚动数值不在其列。**v0.3 扩 I6 后抓住**（D-11）。本条是 I6 定义太窄的活证据
- **最隐蔽的一类**：source 真、quote 准、时点失效

### GT-S5 · 单句多源合成（Law 2 对偶）
- 素材：长鑫过会（stcn）+ 美光万亿（cls），两条独立、各自正确
- 注入：单句内用"同期"连词捆绑，暗示关联，而两源互不提及对方
- 期望：**I1 / RF-2** synthesis violation，拆句
- 合法对照：若用同时并列两事件的源（如新浪/TechWeb 长鑫稿），按该源自身并列方式写、不自加因果连词

---

## 覆盖矩阵

| 陷阱类型 | 样本 |
|---|---|
| 伪双源（同域转载/聚合） | GT-R1 |
| 派生指标口径分歧 | GT-R2, GT-R6 |
| 跨日自我更正 | GT-R3 |
| 时间窗假矛盾 | GT-R4 |
| 缺 primary（Gate 0） | GT-R5 |
| 无归属情绪 | GT-R7 |
| 纯数字错位 | GT-S1 |
| 纯时态错误 | GT-S2 |
| quoted vs model inference | GT-S3a, GT-S3b |
| 过时事实 | GT-S4 |
| 单句多源合成 | GT-S5 |

---

## 回归用法

1. 每条样本编码为 `(quote_pool, writer_output_or_claim, expected_verdict)` fixture。
2. `expected_verdict` 含：命中的 invariant/RF 编号、最终 disposition（pass/drop/rewrite/reject/correction）。
3. `v0.2-gap` 样本的 expected_verdict 在 v0.3 下应从"漏检"翻转为"抓住"——这是 v0.2→v0.3 修订有效性的回归证明。
4. 契约任何 version bump 触发本集全量回归（见 `DECISIONS.md` ADR 流程）。
5. 待补：GT-S1/S2 的 primary-source 版本，用于纯测 B4 judge 语义层（当前暂缺，judge 回归覆盖不完整，记为已知缺口）。
