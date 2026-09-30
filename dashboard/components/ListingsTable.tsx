"use client";

import { Fragment, useMemo, useState } from "react";

type Listing = {
  source: string;
  id: string;
  title: string;
  company: string | null;
  url: string;
  match_pct: number | null;
  notified: boolean;
  reasoning: string | null;
  draft_message: string | null;
  created_at: string;
};

export default function ListingsTable({ listings }: { listings: Listing[] }) {
  const [source, setSource] = useState<string>("all");
  const [notifiedOnly, setNotifiedOnly] = useState(false);
  const [minMatch, setMinMatch] = useState(0);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const filtered = useMemo(() => {
    return listings.filter((listing) => {
      if (source !== "all" && listing.source !== source) return false;
      if (notifiedOnly && !listing.notified) return false;
      if ((listing.match_pct ?? 0) < minMatch) return false;
      return true;
    });
  }, [listings, source, notifiedOnly, minMatch]);

  return (
    <div>
      <div className="flex gap-4 mb-4 items-center">
        <select value={source} onChange={(e) => setSource(e.target.value)} className="border rounded px-2 py-1">
          <option value="all">All sources</option>
          <option value="getonbrd">GetOnBoard</option>
          <option value="computrabajo">Computrabajo</option>
        </select>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={notifiedOnly}
            onChange={(e) => setNotifiedOnly(e.target.checked)}
          />
          Notified only
        </label>
        <label className="flex items-center gap-1">
          Min match %
          <input
            type="number"
            value={minMatch}
            onChange={(e) => setMinMatch(Number(e.target.value))}
            className="border rounded px-2 py-1 w-20"
          />
        </label>
      </div>

      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b">
            <th className="p-2">Source</th>
            <th className="p-2">Title</th>
            <th className="p-2">Company</th>
            <th className="p-2">Match %</th>
            <th className="p-2">Notified</th>
            <th className="p-2">Date</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((listing) => {
            const key = `${listing.source}:${listing.id}`;
            const isExpanded = expandedKey === key;
            return (
              <Fragment key={key}>
                <tr
                  className="border-b cursor-pointer hover:bg-gray-50"
                  onClick={() => setExpandedKey(isExpanded ? null : key)}
                >
                  <td className="p-2">{listing.source}</td>
                  <td className="p-2">
                    <a href={listing.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                      {listing.title}
                    </a>
                  </td>
                  <td className="p-2">{listing.company}</td>
                  <td className="p-2">{listing.match_pct ?? "-"}</td>
                  <td className="p-2">{listing.notified ? "yes" : "no"}</td>
                  <td className="p-2">{new Date(listing.created_at).toLocaleDateString()}</td>
                </tr>
                {isExpanded && (
                  <tr className="border-b bg-gray-50">
                    <td colSpan={6} className="p-4">
                      <p><strong>Reasoning:</strong> {listing.reasoning ?? "n/a"}</p>
                      <p className="mt-2"><strong>Draft message:</strong> {listing.draft_message ?? "n/a"}</p>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
