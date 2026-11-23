import bcrypt from 'bcryptjs'
import { db } from '@/lib/db'
import { cookies } from 'next/headers'

export interface SessionUser {
  id: string
  username: string
  email: string
  avatar?: string
  provider?: string
}

const SESSION_COOKIE_NAME = 'deadcodex_session'
const SESSION_SECRET = process.env.SESSION_SECRET || 'deadcodex-secret-key-change-in-production'

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, 12)
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash)
}

export async function createUser(email: string, username: string, password: string, provider: string = 'email') {
  const hashedPassword = await hashPassword(password)
  
  return db.user.create({
    data: {
      email,
      username,
      password: hashedPassword,
      provider,
      emailVerified: true,
    },
  })
}

export async function createOAuthUser(email: string, username: string, provider: string, providerId: string) {
  return db.user.create({
    data: {
      email,
      username,
      provider,
      providerId,
      emailVerified: true,
    },
  })
}

export async function findUserByEmail(email: string) {
  return db.user.findUnique({
    where: { email },
  })
}

export async function findUserById(id: string) {
  return db.user.findUnique({
    where: { id },
    include: {
      settings: true,
    },
  })
}

export async function setSession(user: SessionUser) {
  const cookieStore = await cookies()
  const sessionData = JSON.stringify({
    userId: user.id,
    username: user.username,
    email: user.email,
    avatar: user.avatar,
    provider: user.provider,
  })
  
  const encodedSession = Buffer.from(sessionData).toString('base64')
  
  cookieStore.set(SESSION_COOKIE_NAME, encodedSession, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 7, // 7 days
    path: '/',
  })
}

export async function getSession(): Promise<SessionUser | null> {
  const cookieStore = await cookies()
  const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME)
  
  if (!sessionCookie) {
    return null
  }
  
  try {
    const sessionData = JSON.parse(Buffer.from(sessionCookie.value, 'base64').toString())
    return sessionData as SessionUser
  } catch {
    return null
  }
}

export async function clearSession() {
  const cookieStore = await cookies()
  cookieStore.delete(SESSION_COOKIE_NAME)
}

export async function getCurrentUser(): Promise<SessionUser | null> {
  const session = await getSession()
  if (!session) {
    return null
  }
  
  const user = await findUserById(session.id)
  if (!user) {
    await clearSession()
    return null
  }
  
  return {
    id: user.id,
    username: user.username,
    email: user.email,
    avatar: user.avatar || undefined,
    provider: user.provider || undefined,
  }
}
