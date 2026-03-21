import { useEffect, useState } from "react";

export default function SearchBar({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    const t = setTimeout(() => onChange(draft), 500);
    return () => clearTimeout(t);
  }, [draft, onChange]);

  return (
    <input
      className="input"
      placeholder="Поиск по названию/номеру"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
    />
  );
}
