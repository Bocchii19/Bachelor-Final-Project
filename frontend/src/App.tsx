import { RouterProvider } from 'react-router-dom'
import { Toaster } from 'sonner'

import { router } from '@/app/router'

function App() {
  return (
    <>
      <RouterProvider router={router} />
      <Toaster
        position="top-right"
        richColors
        toastOptions={{
          classNames: {
            toast:
              '!rounded-[22px] !border !border-neutral-300 !bg-white !text-neutral-950 !shadow-[0_20px_50px_rgba(15,23,42,0.12)]',
            title: '!text-neutral-950',
            description: '!text-neutral-600',
          },
        }}
      />
    </>
  )
}

export default App
