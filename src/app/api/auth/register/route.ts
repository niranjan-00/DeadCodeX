import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'
import { createUser, findUserByEmail, setSession, hashPassword } from '@/lib/auth'
import { db } from '@/lib/db'

const registerSchema = z.object({
  username: z.string().min(3, 'Username must be at least 3 characters').max(50, 'Username must not exceed 50 characters'),
  email: z.string().email('Invalid email address'),
  password: z.string().min(6, 'Password must be at least 6 characters'),
})

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const validatedData = registerSchema.parse(body)

    // Check if user already exists
    const existingUser = await findUserByEmail(validatedData.email)
    
    if (existingUser) {
      if (existingUser.username === validatedData.username) {
        return NextResponse.json(
          { error: 'Username already exists' },
          { status: 400 }
        )
      }
      return NextResponse.json(
        { error: 'Email already registered' },
        { status: 400 }
      )
    }

    // Create user
    const user = await createUser(
      validatedData.email,
      validatedData.username,
      validatedData.password,
      'email'
    )

    // Create default settings
    await db.settings.create({
      data: {
        userId: user.id,
      },
    })

    // Set session
    await setSession({
      id: user.id,
      username: user.username,
      email: user.email,
      provider: 'email',
    })

    return NextResponse.json({
      message: 'Account created successfully',
      user: {
        id: user.id,
        username: user.username,
        email: user.email,
      },
    }, { status: 201 })
  } catch (error) {
    if (error instanceof z.ZodError) {
      return NextResponse.json(
        { error: 'Invalid input data', details: error.errors },
        { status: 400 }
      )
    }

    console.error('Registration error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}
