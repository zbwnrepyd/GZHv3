# Contracts

`contracts/` 存放跨模块共享的数据契约（Goal 一产出）：

- `render_contract.schema.json`：JSON Schema Draft 2020-12，定义 RenderContract 结构（version/company/cards/warnings），字段状态白名单 7 项，媒体状态白名单 5 项
- `asset_keys.json`：9 个 v3 媒体键注册表（logo/website_screenshot/product_main/founder_photo/customer_logos/chart_competitive/chart_ecosystem/flywheel/timeline），按 required/optional 分类
- `card_sets/v3.json`：v3 套卡 8 张卡片定义（card_id + fields + media），ID 唯一（v3_card_01~08）

维护约定：
- 修改契约时同步 `webapp/services/contract_validator.py` 和测试
- `customer_logos` 是 v3 新增槽位（旧版缺失），fallback 为文本列表
- 不在这里存放真实公司数据、数据库文件或运行时缓存
