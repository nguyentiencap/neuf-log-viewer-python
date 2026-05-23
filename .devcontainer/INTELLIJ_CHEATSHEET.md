# IntelliJ DevContainer Cheat Sheet

## 🎯 Nhanh Nhất

```powershell
# Setup lần đầu (2-3 phút)
.\devcontainer.ps1 setup

# Chạy API
.\devcontainer.ps1 api

# Chạy tests
.\devcontainer.ps1 test

# Mở shell
.\devcontainer.ps1 shell

# Dừng
.\devcontainer.ps1 stop
```

## ⚡ IntelliJ Settings (Làm 1 lần)

1. **File** → **Settings** (Ctrl+Alt+S)
2. **Build, Execution, Deployment** → **Docker** → Verify connected
3. **Project** → **Python Interpreter** → **Add via Docker Compose**
   - File: `.devcontainer/docker-compose.yml`
   - Service: `dev`
4. Click **OK** × 2

Done! ✓

## 🏃 Chạy Code từ IntelliJ

| Tác vụ | Cách làm |
|--------|---------|
| FastAPI | Run menu → Select "FastAPI Server" → Shift+F10 |
| Tests | Right-click test file → Run 'pytest' |
| Debug | Đặt breakpoint → Click 🐛 debug icon |
| Terminal | Alt+F12 → `docker exec -it neuf-log-viewer-dev bash` |

## 📝 Cấu Trúc File

```
project/
├── .devcontainer/
│   ├── docker-compose.yml    ← Dùng cái này
│   ├── Dockerfile            ← Custom image
│   ├── devcontainer.json     ← Cho VS Code
│   ├── INTELLIJ_SETUP.md     ← Chi tiết cấu hình
│   └── README.md             ← Hướng dẫn chung
├── .idea/
│   └── runConfigurations/    ← Run configs
├── Makefile                  ← Cho Linux/Mac
├── devcontainer.ps1          ← PowerShell script
├── DEVCONTAINER_INTELLIJ.md  ← Hướng dẫn này
└── src/
```

## 🚨 Troubleshooting Nhanh

| Problem | Solution |
|---------|----------|
| Docker not found | Open Docker Desktop |
| No Python interpreter | Settings → Python Interpreter → Remove old + Add new |
| ModuleNotFoundError | `.\devcontainer.ps1 install-deps` |
| Port 8000 in use | Kill process: `taskkill /PID <PID> /F` |
| Container won't start | `docker-compose -f .devcontainer/docker-compose.yml build --no-cache` |

## 💻 PowerShell Script

```powershell
# View all commands
.\devcontainer.ps1 help

# Top commands
.\devcontainer.ps1 setup         # Setup (build + start)
.\devcontainer.ps1 start         # Start container
.\devcontainer.ps1 stop          # Stop container
.\devcontainer.ps1 shell         # Open shell
.\devcontainer.ps1 test          # Run tests
.\devcontainer.ps1 test-cov      # Tests + coverage
.\devcontainer.ps1 format        # Format with Black
.\devcontainer.ps1 lint          # Lint with Pylint
.\devcontainer.ps1 type-check    # MyPy type check
.\devcontainer.ps1 api           # Run FastAPI
.\devcontainer.ps1 logs          # View logs
.\devcontainer.ps1 clean         # Stop + cleanup
```

## 🐳 Manual Docker Commands

```bash
# Start container
docker-compose -f .devcontainer/docker-compose.yml up -d

# Open shell
docker exec -it neuf-log-viewer-dev bash

# View logs
docker-compose -f .devcontainer/docker-compose.yml logs -f

# Stop container
docker-compose -f .devcontainer/docker-compose.yml down

# Rebuild
docker-compose -f .devcontainer/docker-compose.yml build --no-cache
```

## 📦 Container Info

| Property | Value |
|----------|-------|
| Name | `neuf-log-viewer-dev` |
| Python | 3.11 |
| Port (API) | 8000 |
| Port (Frontend) | 3000 |
| Working Dir | `/workspace` |

## 🎓 Lần Đầu?

1. ✅ Mở project trong IntelliJ
2. ✅ Cấu hình Docker (Settings → Docker)
3. ✅ Cấu hình Python Interpreter (Settings → Python Interpreter)
4. ✅ Verify: Settings → Python Interpreter (nên hiển thị `/usr/local/bin/python` từ container)
5. ✅ Chạy: Run menu → FastAPI Server → Shift+F10

## 📚 Files to Read

- `DEVCONTAINER_INTELLIJ.md` - Hướng dẫn chi tiết (bắt buộc)
- `.devcontainer/INTELLIJ_SETUP.md` - Setup IntelliJ step-by-step
- `.devcontainer/README.md` - Hướng dẫn chung
- `Makefile` / `devcontainer.ps1` - Dùng lệnh dòng lệnh

## ✅ Checklist

- [ ] Docker Desktop cài và chạy
- [ ] Docker kết nối với IntelliJ (Settings → Docker)
- [ ] Python Interpreter cấu hình
- [ ] `.\devcontainer.ps1 setup` thành công
- [ ] FastAPI Server run được (port 8000)
- [ ] Tests chạy được
- [ ] Debugger hoạt động

Good to go! 🚀

