import anthropic

# ============================================================
# 在这里填入你的 Anthropic API Key（格式：sk-ant-...）
# web_fetch 是 Anthropic 托管的服务器端工具，必须使用真实的
# Anthropic API Key，不能使用 DeepSeek 等第三方 API Key。
# ============================================================
ANTHROPIC_API_KEY = "sk-ant-在这里填入你的Key"

# 使用真实的 Anthropic API（强制走 api.anthropic.com，不走 DeepSeek）
client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url="https://api.anthropic.com",
)

response = client.messages.create(
    model="claude-opus-4-7",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": "Please analyze the content at https://example.com",
        }
    ],
    tools=[{"type": "web_fetch_20260209", "name": "web_fetch"}],
)

for block in response.content:
    if block.type == "text":
        print(block.text)
    elif block.type == "server_tool_use":
        print(f"[工具调用] {block.name}: {block._input}")
    elif block.type == "web_fetch_tool_result":
        print(f"[抓取结果] {block.content}")

print(f"\nstop_reason: {response.stop_reason}")
