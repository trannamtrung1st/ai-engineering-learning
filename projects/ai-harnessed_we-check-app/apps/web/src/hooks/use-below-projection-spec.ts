import { useEffect, useState } from "react";

export const PROJECTION_MIN_WIDTH = 1280;
export const PROJECTION_MIN_HEIGHT = 720;

/** NFR-20 — detect viewport below classroom projector minimum */
export function useBelowProjectionSpec(): boolean {
  const [below, setBelow] = useState(false);

  useEffect(() => {
    const check = () => {
      setBelow(
        window.innerWidth < PROJECTION_MIN_WIDTH ||
          window.innerHeight < PROJECTION_MIN_HEIGHT,
      );
    };

    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  return below;
}
