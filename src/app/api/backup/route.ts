import { NextRequest, NextResponse } from 'next/server'
import { getCurrentUser } from '@/lib/auth'
import { db } from '@/lib/db'

export async function POST(request: NextRequest) {
  try {
    const user = await getCurrentUser()
    
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    // Get all user data
    const scans = await db.scan.findMany({
      where: { userId: user.id },
      include: {
        codeAnalyses: true,
      },
    })

    const settings = await db.settings.findUnique({
      where: { userId: user.id },
    })

    // Create backup data
    const backupData = {
      user: {
        id: user.id,
        username: user.username,
        email: user.email,
      },
      settings,
      scans,
      exportedAt: new Date().toISOString(),
    }

    // Create backup record
    await db.backup.create({
      data: {
        userId: user.id,
        name: `backup_${Date.now()}`,
        type: 'full',
        filePath: JSON.stringify(backupData),
        size: JSON.stringify(backupData).length,
        status: 'completed',
      },
    })

    // Update last backup time
    await db.user.update({
      where: { id: user.id },
      data: {
        lastBackupAt: new Date(),
      },
    })

    return NextResponse.json({
      message: 'Backup created successfully',
      backup: backupData,
    })
  } catch (error) {
    console.error('Backup error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

export async function GET(request: NextRequest) {
  try {
    const user = await getCurrentUser()
    
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const backups = await db.backup.findMany({
      where: { userId: user.id },
      orderBy: { createdAt: 'desc' },
      take: 10,
    })

    return NextResponse.json({ backups })
  } catch (error) {
    console.error('Backups fetch error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}
