import { useEffect, useState } from 'react'
import { Boxes, ShieldCheck, Store } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ErrorState } from '@/components/ui/EmptyState'
import { Skeleton } from '@/components/ui/Skeleton'
import { userService } from '@/services/userService'
import type { Product } from '@/types'

const icons = {
  blue: Store,
  sky: ShieldCheck,
  green: Boxes,
}

const tones = {
  blue: 'bg-primary/10 text-primary',
  sky: 'bg-accent/10 text-accent',
  green: 'bg-success/10 text-success',
}

export function ProductsPage() {
  const [products, setProducts] = useState<Product[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    userService
      .getProducts()
      .then(setProducts)
      .catch(() => setError('Unable to load products'))
  }, [])

  if (error) return <ErrorState title="Unable to load products" message={error} />
  if (!products) return <Skeleton className="h-48" />

  return (
    <div>
      <PageHeader title="Other Products" subtitle="Additional tools from the AndroGuard family." />
      <div className="grid gap-4 md:grid-cols-3">
        {products.map((product) => {
          const Icon = icons[product.tone]
          return (
            <Card key={product.id} className="p-5">
              <span className={`grid h-11 w-11 place-items-center rounded-xl ${tones[product.tone]}`}>
                <Icon size={20} />
              </span>
              <h2 className="mt-4 text-base font-semibold text-ink">{product.name}</h2>
              <p className="mt-2 text-sm text-muted">{product.description}</p>
              <Button variant="outline" className="mt-5" onClick={() => window.open(product.href, '_self')}>
                View Product
              </Button>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
