import type { Product, User } from '@/types'

// Demo identity used only by the local sign-in helpers (Google button / forgot password mocks).
export const DEMO_PASSWORD = 'PlayGuard123'

export const demoUser: User = {
  id: 'user-1',
  fullName: 'Alex Rivera',
  companyName: 'Northstar Apps',
  email: 'alex@northstar.dev',
  avatarInitials: 'AR',
}

export const products: Product[] = [
  {
    id: 'store-copy',
    name: 'Store Copy Review',
    description: 'Check Play Store listing copy, screenshots, and metadata before you submit.',
    href: '#',
    tone: 'blue',
  },
  {
    id: 'privacy-mapper',
    name: 'Privacy Mapper',
    description: 'Map SDK data flows to Privacy Policy and Data Safety declarations.',
    href: '#',
    tone: 'sky',
  },
  {
    id: 'release-guard',
    name: 'Release Guard',
    description: 'Run a final pre-release checklist for signing, targeting, and policy status.',
    href: '#',
    tone: 'green',
  },
]
