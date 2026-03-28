import { useEffect } from "react";

export function useKeyboard(shortcuts: Record<string, () => void>): void {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      // Build key string: "Meta+k", "Shift+Enter", or just "k"
      const parts: string[] = [];
      if (e.metaKey) parts.push("Meta");
      if (e.ctrlKey) parts.push("Control");
      if (e.altKey) parts.push("Alt");
      if (e.shiftKey) parts.push("Shift");
      parts.push(e.key);

      const combo = parts.join("+");
      const cb = shortcuts[combo] ?? shortcuts[e.key];

      if (cb) {
        e.preventDefault();
        cb();
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [shortcuts]);
}
