import { useEffect, useRef, useState } from "react";

/**
 * A canvas has two sizes: the CSS box it occupies and the bitmap it draws
 * into. If the bitmap is set once and the box later changes, the browser
 * stretches the old bitmap to fit and the drawing is distorted — a circuit
 * comes out squashed. This reports the box size so the bitmap can be resized
 * and the panel redrawn whenever it changes.
 */
export function useCanvasSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () =>
      setSize((current) => {
        const width = element.clientWidth;
        const height = element.clientHeight;
        return current.width === width && current.height === height ? current : { width, height };
      });
    measure();
    if (typeof ResizeObserver === "undefined") return;   // jsdom in tests
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { ref, size };
}
