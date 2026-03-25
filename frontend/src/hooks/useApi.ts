import { useEffect, useState } from "react";

export function useApi<T>(request: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    request()
      .then((res) => mounted && setData(res))
      .catch((e) => mounted && setError((e as Error).message))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  return { data, loading, error };
}
