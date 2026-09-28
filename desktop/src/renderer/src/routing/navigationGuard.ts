let activeGuard: ((nextHash: string) => boolean) | null = null
let allowedHash: string | null = null

export function registerHashNavigationGuard(guard: (nextHash: string) => boolean): () => void {
  activeGuard = guard
  return () => {
    if (activeGuard === guard) activeGuard = null
    allowedHash = null
  }
}

export function allowNextHashNavigation(nextHash: string): void {
  allowedHash = nextHash
}

export function canAcceptHashNavigation(nextHash: string): boolean {
  if (allowedHash === nextHash) {
    allowedHash = null
    return true
  }
  return canLeaveDirtyWorkspace(nextHash)
}

export function canLeaveDirtyWorkspace(target: string): boolean {
  return activeGuard?.(target) ?? true
}
