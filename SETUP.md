# DeadCodeX - Setup & Run Guide

## 📋 Prerequisites

Before you begin, ensure you have the following installed:

- **Node.js** (v18 or higher) - [Download](https://nodejs.org/)
- **Bun** (recommended) or npm/yarn
  - Bun: `curl -fsSL https://bun.sh/install | bash`
  - npm: Comes with Node.js
- **Git** (optional, for cloning)

## 🚀 Quick Start (5 Minutes)

### Option 1: Using Bun (Recommended)

```bash
# 1. Extract the zip file
unzip deadcodex.zip
cd deadcodex

# 2. Install dependencies
bun install

# 3. Set up the database
bun run db:push

# 4. Start the development server
bun run dev
```

### Option 2: Using npm

```bash
# 1. Extract the zip file
unzip deadcodex.zip
cd deadcodex

# 2. Install dependencies
npm install

# 3. Set up the database
npm run db:push

# 4. Start the development server
npm run dev
```

### Option 3: Using yarn

```bash
# 1. Extract the zip file
unzip deadcodex.zip
cd deadcodex

# 2. Install dependencies
yarn install

# 3. Set up the database
yarn db:push

# 4. Start the development server
yarn dev
```

## 🌐 Accessing the Application

Once the server starts, open your browser and navigate to:

**Local:** http://localhost:3000

## 📝 Configuration

### Environment Variables

The application includes a default `.env` file. If you need to customize, create a `.env` file in the root directory:

```env
# Database
DATABASE_URL="file:./db/custom.db"

# Session Security (CHANGE THIS IN PRODUCTION!)
SESSION_SECRET="deadcodex-secret-key-change-in-production"

# OAuth Providers (Optional - for future implementation)
# GOOGLE_CLIENT_ID="your-google-client-id"
# GOOGLE_CLIENT_SECRET="your-google-client-secret"
# GITHUB_CLIENT_ID="your-github-client-id"
# GITHUB_CLIENT_SECRET="your-github-client-secret"

# AWS S3 (Optional - for future implementation)
# AWS_ACCESS_KEY_ID="your-access-key"
# AWS_SECRET_ACCESS_KEY="your-secret-key"
# AWS_REGION="us-east-1"
```

## 🗄️ Database Setup

### Default (SQLite)
The project comes with SQLite pre-configured. Just run:
```bash
bun run db:push
```

This will create the database file at `./db/custom.db` and set up all tables.

### Using PostgreSQL (Optional)
If you prefer PostgreSQL:

1. Install PostgreSQL client library:
```bash
bun add pg
```

2. Update `DATABASE_URL` in `.env`:
```env
DATABASE_URL="postgresql://user:password@localhost:5432/deadcodex"
```

3. Update `prisma/schema.prisma`:
```prisma
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}
```

4. Push the schema:
```bash
bun run db:push
```

## 📦 Available Scripts

```bash
# Development
bun run dev          # Start development server (localhost:3000)

# Database Management
bun run db:push       # Push schema changes to database
bun run db:generate   # Generate Prisma Client
bun run db:migrate    # Run migrations
bun run db:reset      # Reset database (DESTRUCTIVE!)

# Build & Production
bun run build         # Build for production
bun run start         # Start production server

# Code Quality
bun run lint          # Run ESLint
```

## 🎯 Using the Application

### 1. Sign Up
- Visit http://localhost:3000
- Click "Get Started"
- Fill in username, email, and password
- Click "Create Account"

### 2. Upload Code for Analysis
- Click "Upload" in the sidebar
- Choose upload method:
  - **Files**: Drag & drop or browse
  - **GitHub**: Enter repo URL (placeholder)
  - **Drive**: Enter Drive URL (placeholder)
  - **AWS**: Enter bucket details (placeholder)
- Click "Start Analysis"

### 3. View Analysis Results
- See detected errors and warnings
- Read AI suggestions
- Preview code with fixes
- Download individual files

### 4. Clean Up Code
- Select files to clean
- Click "Clean Up Selected"
- Review AI-generated fixes
- Download cleaned code

### 5. Manage Settings
- Click "Settings" in sidebar
- Configure preferences
- Set backup frequency
- Choose language preferences

## 🛠️ Troubleshooting

### Port 3000 Already in Use

If you get an error that port 3000 is in use:

**Option 1:** Stop the other process using port 3000
```bash
# Find the process
lsof -ti:3000
# Kill it
kill -9 $(lsof -ti:3000)
```

**Option 2:** Use a different port (edit `package.json`):
```json
"scripts": {
  "dev": "next dev -p 3001"
}
```

### Database Lock Issues

If you encounter database lock errors:
```bash
# Remove the lock file
rm -f prisma/*.db-journal

# Or reset the database (WARNING: This deletes all data!)
bun run db:reset
```

### Module Not Found Errors

If you see "module not found" errors:
```bash
# Clear node_modules and reinstall
rm -rf node_modules bun.lockb
bun install
```

### Build Errors

If the build fails:
```bash
# Clear Next.js cache
rm -rf .next

# Try building again
bun run build
```

### Permission Errors

If you encounter permission errors:
```bash
# On Linux/Mac, fix permissions
chmod -R 755 .

# On Windows, run terminal as Administrator
```

## 🐛 Development Tips

### Hot Reload
The development server supports hot reload. Changes to files will automatically reflect in the browser.

### Database Changes
When modifying `prisma/schema.prisma`:
```bash
# Apply changes to database
bun run db:push

# Regenerate Prisma Client (if needed)
bun run db:generate
```

### Viewing Logs
The dev server logs to both console and `dev.log`:
```bash
# View logs in real-time
tail -f dev.log

# View last 100 lines
tail -100 dev.log
```

### Running Linter
```bash
# Check code quality
bun run lint

# Auto-fix some issues (if configured)
bun run lint --fix
```

## 📁 Project Structure

```
deadcodex/
├── prisma/
│   └── schema.prisma          # Database schema
├── src/
│   ├── app/                   # Next.js App Router pages
│   │   ├── analysis/[id]/     # Analysis results page
│   │   ├── cleanup/[id]/      # Code cleanup page
│   │   ├── dashboard/         # User dashboard
│   │   ├── login/            # Login page
│   │   ├── page.tsx          # Landing page
│   │   ├── register/         # Registration page
│   │   ├── settings/         # Settings page
│   │   ├── upload/           # Upload page
│   │   └── api/             # API routes
│   │       ├── auth/         # Authentication endpoints
│   │       ├── analyze/      # AI analysis endpoints
│   │       ├── backup/       # Backup endpoints
│   │       ├── scans/        # Scan management
│   │       ├── settings/     # Settings endpoints
│   │       └── user/        # User endpoints
│   ├── components/            # React components
│   │   └── ui/              # shadcn/ui components
│   ├── hooks/                # Custom React hooks
│   └── lib/                 # Utilities & helpers
├── db/                      # Database files (auto-created)
│   └── custom.db            # SQLite database file
├── public/                   # Static assets
├── .env                     # Environment variables
├── .env.example             # Environment template
├── package.json             # Dependencies & scripts
├── prisma/schema.prisma    # Database schema
├── tsconfig.json           # TypeScript config
├── tailwind.config.ts     # Tailwind config
└── next.config.ts         # Next.js config
```

## 🔒 Security Notes for Production

### Before Deploying to Production:

1. **Change SESSION_SECRET**
   ```env
   SESSION_SECRET="generate-a-secure-random-string-here"
   ```
   Generate a secure secret: `openssl rand -base64 32`

2. **Use Environment Variables**
   - Never commit `.env` file
   - Use `.env.example` as template
   - Set environment variables in your hosting platform

3. **Database Security**
   - Use PostgreSQL for production
   - Enable SSL connections
   - Use strong database credentials

4. **Enable HTTPS**
   - Always use HTTPS in production
   - Configure SSL certificates

5. **OAuth Security**
   - Use secure callback URLs
   - Enable PKCE for OAuth
   - Store secrets securely

## 🚢 Production Deployment

### Vercel (Recommended)
```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel
```

### Railway
```bash
# Install Railway CLI
npm i -g @railway/cli

# Deploy
railway up
```

### Docker
```bash
# Build Docker image
docker build -t deadcodex .

# Run container
docker run -p 3000:3000 deadcodex
```

### Traditional VPS
```bash
# Build
bun run build

# Start production server
bun run start
```

## 📚 Additional Resources

- [Next.js Documentation](https://nextjs.org/docs)
- [Prisma Documentation](https://www.prisma.io/docs)
- [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- [shadcn/ui Documentation](https://ui.shadcn.com)
- [TypeScript Documentation](https://www.typescriptlang.org/docs)

## 🤝 Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the code comments
3. Check browser console for errors
4. Review server logs in `dev.log`

## 📝 License

This project is provided as-is for educational and commercial use.

---

**Happy Coding! 🎉**
