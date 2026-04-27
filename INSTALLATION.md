# DeadCodeX - Complete Installation Guide

## 🎯 What is DeadCodeX?

DeadCodeX is an AI-powered code analysis platform that helps you detect errors, fix issues, and improve code quality automatically. It supports multiple programming languages and various upload sources including files, GitHub, Google Drive, and AWS.

## 📋 System Requirements

Before installing DeadCodeX, ensure your system meets these requirements:

- **Node.js**: Version 18.x or higher
- **Bun**: 1.x or higher (recommended) OR npm/yarn
- **Disk Space**: Minimum 500MB free space
- **Memory**: Minimum 2GB RAM (4GB recommended)
- **OS**: Windows, macOS, or Linux

## 🚀 Quick Installation (5 Minutes)

### Step 1: Extract the Archive

Extract the `DeadCodeX.zip` file to your desired location:

```bash
# On Linux/Mac
unzip DeadCodeX.zip
cd DeadCodeX

# On Windows
# Right-click and "Extract All"
# Then navigate to the extracted folder in terminal
```

### Step 2: Install Dependencies

Choose one of the following options based on your package manager:

#### Option A: Using Bun (Recommended - Fastest)
```bash
# Install Bun if you haven't already
curl -fsSL https://bun.sh/install | bash

# Install dependencies
bun install
```

#### Option B: Using npm
```bash
# npm comes with Node.js
npm install
```

#### Option C: Using yarn
```bash
# Install yarn if you haven't already
npm install -g yarn

# Install dependencies
yarn install
```

### Step 3: Set Up Environment Variables

```bash
# Copy the example environment file
cp .env.example .env
```

For development, the default values in `.env` will work. For production, edit `.env` and update:

```env
SESSION_SECRET="generate-a-secure-random-string"
```

Generate a secure secret:
```bash
openssl rand -base64 32
```

### Step 4: Initialize the Database

```bash
# Using Bun
bun run db:push

# Using npm
npm run db:push

# Using yarn
yarn db:push
```

This creates:
- `db/custom.db` - SQLite database file
- All necessary tables (Users, Scans, Files, Settings, Backups)

### Step 5: Start the Development Server

```bash
# Using Bun
bun run dev

# Using npm
npm run dev

# Using yarn
yarn dev
```

The application will start at **http://localhost:3000**

## 🌐 Accessing the Application

1. Open your browser
2. Navigate to **http://localhost:3000**
3. Click "Get Started" to create your account
4. Sign up with email and password

## ✅ Verification

Test that everything is working:

1. **Create Account**: Register a new account
2. **Login**: Sign in with your credentials
3. **Upload Test Code**: Go to Upload page and upload a sample code file
4. **View Analysis**: Check that errors are detected and suggestions provided
5. **Download Results**: Download the cleaned code

## 📁 What's Included?

```
DeadCodeX/
├── prisma/
│   └── schema.prisma          # Database schema
├── src/
│   ├── app/                   # Next.js pages
│   │   ├── analysis/[id]/     # Analysis results
│   │   ├── cleanup/[id]/      # Code cleanup
│   │   ├── dashboard/         # User dashboard
│   │   ├── login/            # Login page
│   │   ├── page.tsx          # Landing page
│   │   ├── register/         # Registration page
│   │   ├── settings/         # Settings
│   │   └── upload/           # Upload page
│   ├── components/           # React components
│   │   └── ui/              # shadcn/ui components
│   ├── hooks/               # Custom hooks
│   └── lib/                 # Utilities
├── public/                   # Static assets
├── .env.example             # Environment template
├── .env                     # Your environment variables
├── package.json             # Dependencies
├── tsconfig.json           # TypeScript config
├── tailwind.config.ts      # Tailwind config
└── next.config.ts          # Next.js config
```

## 🔧 Advanced Configuration

### Using PostgreSQL Instead of SQLite

If you prefer PostgreSQL:

1. Install PostgreSQL
2. Create a database:
   ```bash
   createdb deadcodex
   ```

3. Update `.env`:
   ```env
   DATABASE_URL="postgresql://user:password@localhost:5432/deadcodex"
   ```

4. Update `prisma/schema.prisma`:
   ```prisma
   datasource db {
     provider = "postgresql"
     url      = env("DATABASE_URL")
   }
   ```

5. Install PostgreSQL client:
   ```bash
   bun add pg
   ```

6. Push schema:
   ```bash
   bun run db:push
   ```

### Changing the Port

If port 3000 is already in use:

1. Edit `package.json`:
   ```json
   "scripts": {
     "dev": "next dev -p 3001"
   }
   ```

2. Restart the server

### Enabling OAuth (Optional)

For Google and GitHub login:

1. Create OAuth apps in Google Console and GitHub Developer Settings
2. Update `.env`:
   ```env
   GOOGLE_CLIENT_ID="your-client-id"
   GOOGLE_CLIENT_SECRET="your-client-secret"
   GITHUB_CLIENT_ID="your-client-id"
   GITHUB_CLIENT_SECRET="your-client-secret"
   ```

3. Implement OAuth handlers (future feature)

## 🛠️ Common Installation Issues

### Issue: Port 3000 Already in Use
**Solution:**
```bash
# Kill process using port 3000
lsof -ti:3000 | xargs kill -9

# Or use a different port (edit package.json)
```

### Issue: Module Not Found Errors
**Solution:**
```bash
# Clear and reinstall
rm -rf node_modules
rm bun.lockb  # or package-lock.json
bun install
```

### Issue: Database Lock Error
**Solution:**
```bash
# Remove lock file
rm -f prisma/*.db-journal
# Or reset database
bun run db:reset
```

### Issue: Prisma Client Generation Error
**Solution:**
```bash
bun run db:generate
bun run db:push
```

### Issue: TypeScript Build Errors
**Solution:**
```bash
# Clear Next.js cache
rm -rf .next

# Restart dev server
bun run dev
```

## 📦 Available Scripts

```bash
# Development
bun run dev          # Start dev server (port 3000)

# Database
bun run db:push      # Push schema to database
bun run db:generate  # Generate Prisma Client
bun run db:migrate   # Run migrations
bun run db:reset     # Reset database (deletes all data!)

# Build & Production
bun run build        # Build for production
bun run start        # Start production server

# Code Quality
bun run lint         # Run ESLint
```

## 🚀 Production Deployment

### Option 1: Vercel (Recommended)

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel
```

### Option 2: Railway

```bash
# Install Railway CLI
npm i -g @railway/cli

# Deploy
railway up
```

### Option 3: Docker

1. Create `Dockerfile` (not included, needs to be created)
2. Build and run:
   ```bash
   docker build -t deadcodex .
   docker run -p 3000:3000 deadcodex
   ```

### Option 4: Traditional VPS

```bash
# Build the application
bun run build

# Start production server
bun run start
```

## 🔒 Security Checklist Before Going to Production

- [ ] Change `SESSION_SECRET` to a secure random string
- [ ] Set strong database credentials
- [ ] Enable HTTPS
- [ ] Set up proper CORS configuration
- [ ] Configure rate limiting
- [ ] Set up proper logging and monitoring
- [ ] Backup database regularly
- [ ] Review and update dependencies
- [ ] Set up environment variables in hosting platform (not in code)

## 📚 Next Steps

After successful installation:

1. **Read the README.md** - Understand all features
2. **Read SETUP.md** - Learn about configuration
3. **Explore the UI** - Try uploading and analyzing code
4. **Customize Settings** - Configure to your needs
5. **Check Documentation** - Learn advanced features

## 🆘 Getting Help

If you encounter issues:

1. Check the **Troubleshooting** section in SETUP.md
2. Review browser console for errors (F12)
3. Check server logs: `tail -f dev.log`
4. Ensure all dependencies are installed: `bun list`
5. Verify Node.js version: `node --version`

## 📝 Additional Resources

- [Next.js Documentation](https://nextjs.org/docs)
- [Prisma Documentation](https://www.prisma.io/docs)
- [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- [shadcn/ui Documentation](https://ui.shadcn.com)

## ✨ You're Ready!

Your DeadCodeX installation is complete. Start analyzing your code and let AI help you fix errors automatically!

---

**Need Help?** Check SETUP.md for detailed configuration and troubleshooting.
