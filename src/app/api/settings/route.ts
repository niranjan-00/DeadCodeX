import { NextRequest, NextResponse } from 'next/server'
import { getCurrentUser } from '@/lib/auth'
import { db } from '@/lib/db'

export async function GET() {
  try {
    const user = await getCurrentUser()
    
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const settings = await db.settings.findUnique({
      where: { userId: user.id },
    })

    if (!settings) {
      // Create default settings
      const newSettings = await db.settings.create({
        data: {
          userId: user.id,
        },
      })
      return NextResponse.json({ settings: newSettings })
    }

    return NextResponse.json({ settings })
  } catch (error) {
    console.error('Settings fetch error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

export async function POST(request: NextRequest) {
  try {
    const user = await getCurrentUser()
    
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const body = await request.json()
    const { autoCleanup, notifyOnError, backupFrequency, preferredLanguage, theme } = body

    const settings = await db.settings.upsert({
      where: { userId: user.id },
      update: {
        autoCleanup,
        notifyOnError,
        backupFrequency,
        preferredLanguage,
        theme,
      },
      create: {
        userId: user.id,
        autoCleanup,
        notifyOnError,
        backupFrequency,
        preferredLanguage,
        theme,
      },
    })

    return NextResponse.json({
      message: 'Settings saved successfully',
      settings,
    })
  } catch (error) {
    console.error('Settings save error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}
