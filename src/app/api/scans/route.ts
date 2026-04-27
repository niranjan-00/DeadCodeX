import { NextRequest, NextResponse } from 'next/server'
import { getCurrentUser } from '@/lib/auth'
import { db } from '@/lib/db'

export async function GET(request: NextRequest) {
  try {
    const user = await getCurrentUser()

    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const scans = await db.scan.findMany({
      where: { userId: user.id },
      orderBy: { date: 'desc' },
      take: 20,
      include: {
        codeAnalyses: {
          take: 5,
        },
      },
    })

    const totalScans = await db.scan.count({
      where: { userId: user.id },
    })

    const completedScans = await db.scan.count({
      where: {
        userId: user.id,
        status: 'Completed',
      },
    })

    return NextResponse.json({
      scans,
      totalScans,
      completedScans,
    })
  } catch (error) {
    console.error('Error fetching scans:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}
