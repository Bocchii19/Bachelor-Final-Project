import { useEffect, useEffectEvent } from 'react'

import { useAppStore } from '@/store/appStore'

export function useDashboardBootstrap() {
  const bootstrap = useAppStore((state) => state.bootstrap)
  const isBootstrapped = useAppStore((state) => state.isBootstrapped)

  const runBootstrap = useEffectEvent(() => {
    void bootstrap()
  })

  useEffect(() => {
    if (!isBootstrapped) {
      runBootstrap()
    }
  }, [isBootstrapped])
}
