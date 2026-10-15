import { delay } from '@/lib/utils'
import { products } from '@/mock/data'

export const userService = {
  async getProducts() {
    await delay(300)
    return products
  },
}
