# Vercel 部署指南

## 方案一：当前配置（推荐）

当前配置将 dashboard 目录的内容映射到根路径。

### 配置说明
- 根目录 vercel.json 处理路由重写
- API 函数位于 dashboard/api/
- 静态文件位于 dashboard/

### 部署步骤
1. 推送代码到 Git 仓库
2. 在 Vercel 导入项目
3. Vercel 会自动检测 vercel.json 配置
4. 部署完成

## 方案二：设置根目录（更简单）

如果方案一不工作，可以在 Vercel 项目设置中：

1. 进入 Vercel 项目设置
2. 找到 "Build & Development Settings"
3. 设置 "Root Directory" 为 `dashboard`
4. 保存并重新部署

这样 Vercel 会将 dashboard 作为项目根目录，不需要复杂的路由重写。

## 验证部署

部署成功后，访问：
- `/` - 应显示 dashboard 主页
- `/api/trades?limit=10` - 应返回交易数据 JSON
- `/api/gamma/markets?limit=10` - 应返回市场数据 JSON

## 常见问题

### 404 错误
- 检查 Root Directory 是否设置正确
- 检查 vercel.json 配置是否正确
- 查看 Vercel 部署日志

### API 超时
- 增加 functions 配置中的 maxDuration
- 检查 API 调用是否正常

### CORS 错误
- API 文件中已包含 CORS 头设置
- 如果还有问题，检查 Vercel 项目设置中的 CORS 配置
