# 更新日志

## 2025-11-20

### 新增功能
- **大额交易 Outcome 显示**：在 dashboard 的大额交易列表中，鼠标悬停在交易行上时会显示该交易的 outcome 信息（Yes/No）
  - 添加了 tooltip 样式，当鼠标移动到大额交易项时显示
  - tooltip 显示交易的买卖方向（Yes 或 No）
  - 使用霓虹蓝色边框和深色背景的悬浮框显示

### 技术实现
1. 修改 `dashboard/app.js`：
   - 在 `detectAnomalies` 函数中保存交易的 `outcome` 字段
   - 在 `updateWhaleTrades` 函数中添加 tooltip 元素显示 outcome

2. 修改 `dashboard/index.html`：
   - 添加 `.whale-trade-item` 样式设置 relative 定位
   - 添加 `.outcome-tooltip` 样式设置 tooltip 的位置和样式
   - 添加悬停效果，鼠标移到交易项时显示 tooltip

### 使用说明
- 打开 dashboard 页面
- 在右侧的"大额交易"栏目中，将鼠标移动到任意交易行上
- tooltip 会在交易项上方显示，显示格式为 "Outcome: Yes" 或 "Outcome: No"
