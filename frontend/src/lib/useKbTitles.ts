import { useEffect, useState } from "react";

import { getKb } from "@/api";

let cache: Map<string, string> | null = null;
let inflight: Promise<Map<string, string>> | null = null;

async function load(): Promise<Map<string, string>> {
  if (cache) return cache;
  if (inflight) return inflight;
  inflight = getKb()
    .then((standards) => {
      const m = new Map<string, string>();
      for (const s of standards)
        for (const d of s.disclosures) m.set(d.id, d.title);
      cache = m;
      return m;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

export function useKbTitles(): Map<string, string> {
  const [titles, setTitles] = useState<Map<string, string>>(cache ?? new Map());
  useEffect(() => {
    let stale = false;
    void load().then((m) => !stale && setTitles(m));
    return () => {
      stale = true;
    };
  }, []);
  return titles;
}
