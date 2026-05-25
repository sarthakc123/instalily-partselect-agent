"use client";

import { Package, ShoppingCart } from "lucide-react";

import type { PartCard as PartCardData } from "@/lib/types";

export function ProductCard({ part }: { part: PartCardData }) {
  const price = (part.price_cents / 100).toFixed(2);
  return (
    <article className="overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
      <header className="flex items-center gap-2 bg-ps-blue/5 px-4 py-2 text-[11px] uppercase tracking-wider text-ps-blue">
        <Package size={14} />
        <span>Part</span>
      </header>
      <div className="grid grid-cols-[auto,1fr] gap-3 p-4">
        {/* Image placeholder. Real image URL lands when the scraper populates parts.image_url. */}
        <div className="flex h-20 w-20 items-center justify-center rounded-lg bg-surface-muted text-muted-foreground">
          <Package size={28} aria-hidden />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-foreground leading-tight">
            {part.name}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span className="rounded-md bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
              {part.id}
            </span>
            <span>{part.manufacturer}</span>
            <span aria-hidden>·</span>
            <span>{part.appliance_type}</span>
          </div>
          {part.description ? (
            <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
              {part.description}
            </p>
          ) : null}
        </div>
      </div>
      <footer className="flex items-center justify-between border-t border-border bg-surface-muted/40 px-4 py-2.5">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-semibold text-foreground">${price}</span>
          <StockDot inStock={part.in_stock} />
        </div>
        <button
          type="button"
          disabled
          title="Cart is mocked for the case study. Phase 4 wires real cart endpoints."
          className="inline-flex items-center gap-1.5 rounded-lg bg-ps-orange px-3 py-1.5 text-xs font-medium text-white opacity-70 cursor-not-allowed"
        >
          <ShoppingCart size={12} />
          Add to cart
        </button>
      </footer>
    </article>
  );
}

function StockDot({ inStock }: { inStock: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-[11px] ${
        inStock ? "text-emerald-600" : "text-rose-600"
      }`}
    >
      <span
        aria-hidden
        className={`inline-block h-1.5 w-1.5 rounded-full ${
          inStock ? "bg-emerald-500" : "bg-rose-500"
        }`}
      />
      {inStock ? "In stock" : "Out of stock"}
    </span>
  );
}
