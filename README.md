# DeadCodeX 🚀

DeadCodeX is an AI-powered automated dead code detection, code quality analysis, and cleanup platform designed to improve maintainability, reduce technical debt, and optimize software projects.

## 📌 Problem Statement

Modern and legacy codebases often contain:

- Unused variables, imports, functions, and classes
- Duplicate logic
- Dead or unreachable code
- Poor code quality patterns
- Increasing build times
- Difficult maintenance

These issues slow down development and increase technical debt.

---

## 💡 Solution

DeadCodeX intelligently scans source code repositories, uploaded projects, or ZIP files using static analysis + AI-assisted detection to identify unnecessary code, quality issues, and optimization opportunities.

It then provides confidence-based cleanup recommendations.

---

## ✨ Features

### 🚀 Core Features

- 🔍 Detect dead code automatically
- 🤖 AI-powered code analysis
- 🧹 Cleanup recommendations
- 📊 Confidence scoring
- 📄 Export analysis reports
- ⚡ Improve project performance
- 📂 Repository scanning support
- 🔐 Secure uploads

### 📤 Upload Sources

- Manual file upload
- ZIP project upload
- GitHub repository integration
- Cloud source support (future)

### 🛠️ Analysis Features

- Unused imports
- Unused variables
- Unused functions/classes
- Duplicate logic detection
- Unreachable code detection
- File-wise report generation
- Suggestions with severity levels

---

## 🛠 Tech Stack

### Frontend

- HTML5
- Tailwind CSS
- JavaScript

### Backend

- Python Flask / Node.js

### Database

- SQLite / PostgreSQL

### Analysis Engine

- Python AST Parsing
- Rule Engine
- AI Suggestions

---

## 📁 Project Structure

```bash
DeadCodeX/
├── app.py
├── requirements.txt
├── package.json
├── templates/
│   ├── index.html
│   ├── dashboard.html
│   ├── upload.html
│   ├── analysis.html
│   └── settings.html
├── static/
│   ├── css/
│   └── js/
├── uploads/
├── reports/
└── instance/
## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login user
- `POST /api/auth/logout` - Logout user
- `GET /api/auth/session` - Get current session

### User
- `GET /api/user` - Get current user info

### Upload & Analysis
- `POST /api/upload` - Upload code for analysis
- `GET /api/scans` - List all scans
- `GET /api/scans/[id]` - Get scan details
- `POST /api/analyze` - Rectify code with AI

### Settings & Backup
- `GET /api/settings` - Get user settings
- `POST /api/settings` - Update settings
- `POST /api/backup` - Create backup
- `GET /api/backup` - List backups

## Technology Stack

- **Framework**: Next.js 16 with App Router
- **Language**: TypeScript
- **Styling**: Tailwind CSS 4
- **UI Components**: shadcn/ui (Radix UI primitives)
- **Database**: Prisma ORM with SQLite
- **Authentication**: Custom session-based auth
- **File Processing**: unzipper for ZIP extraction
- **Icons**: Lucide React
- **Animations**: Framer Motion
- **Notifications**: Sonner

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `file:./db/custom.db` |
| `SESSION_SECRET` | Secret for session encryption | - |

## OAuth Configuration

To enable OAuth providers (Google, GitHub), add the following to your `.env`:

```env
GOOGLE_CLIENT_ID="your-google-client-id"
GOOGLE_CLIENT_SECRET="your-google-client-secret"
GITHUB_CLIENT_ID="your-github-client-id"
GITHUB_CLIENT_SECRET="your-github-client-secret"
```

Then implement the OAuth callback handlers in `/src/app/api/auth/oauth`.

## Database Schema

### User
- Authentication (email, OAuth)
- Profile information
- OAuth tokens (encrypted)

### Settings
- User preferences
- Auto-cleanup settings
- Notification settings
- Backup configuration

### Scan
- Project information
- Analysis results
- Error and warning counts
- Source tracking (manual, GitHub, Drive, AWS)

### CodeAnalysis
- File-level analysis
- Error details
- Suggestions
- Original and rectified code

### Backup
- Backup history
- Export data
- Size and status

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see LICENSE file for details.

## Support

For issues and questions, please open an issue on GitHub.
=======
# DeadCodeX
>>>>>>> 0dfb62c78b8a30993a5c42a1042bd911e4da8ed5
