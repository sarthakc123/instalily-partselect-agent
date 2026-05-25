"use client";

import { useState } from "react";
import {
  Beaker,
  CircuitBoard,
  Cog,
  DoorClosed,
  Droplets,
  Fan,
  Filter,
  Flame,
  LayoutGrid,
  Lightbulb,
  Lock,
  Package,
  ShoppingCart,
  Snowflake,
  Thermometer,
  Timer,
  ToggleLeft,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";

import type { PartCard as PartCardData } from "@/lib/types";


/**
 * Map part_type (from our seed) to a representative lucide icon. The
 * placeholder shows the icon over a soft gradient tinted by appliance type
 * so the card looks intentional even without product photography.
 *
 * When part.image_url is populated (Phase 2 scrape), the icon is replaced
 * by an <img> with onError fallback back to the icon.
 */
const PART_TYPE_ICON: Record<string, LucideIcon> = {
  ice_maker: Snowflake,
  ice_maker_auger: Snowflake,
  water_filter: Filter,
  water_inlet_valve: Droplets,
  drain_pump: Droplets,
  drain_hose: Droplets,
  spray_arm_upper: Droplets,
  spray_arm_lower: Droplets,
  spray_tower: Droplets,
  drain_pan: Droplets,
  rinse_aid_dispenser: Droplets,
  evaporator_fan_motor: Fan,
  condenser_fan_motor: Fan,
  wash_motor: Fan,
  pump_motor_assembly: Cog,
  start_relay: Zap,
  thermostat: Thermometer,
  thermistor: Thermometer,
  defrost_thermostat: Thermometer,
  defrost_heater: Flame,
  heating_element: Flame,
  thermal_fuse: Zap,
  defrost_timer: Timer,
  defrost_control: CircuitBoard,
  control_board: CircuitBoard,
  timer: Timer,
  door_gasket: DoorClosed,
  door_seal: DoorClosed,
  door_handle: DoorClosed,
  door_switch: ToggleLeft,
  door_latch: Lock,
  door_strike: Lock,
  door_catch: Lock,
  door_hinge: DoorClosed,
  door_spring: Cog,
  light_bulb: Lightbulb,
  filter_assembly: Filter,
  float_switch: ToggleLeft,
  sump_cover: Cog,
  silverware_basket: LayoutGrid,
  lower_rack: LayoutGrid,
  rack_wheel: Cog,
  crisper_drawer: LayoutGrid,
  crisper_cover: LayoutGrid,
  door_bin: LayoutGrid,
  shelf_bracket: Wrench,
  freezer_drawer: LayoutGrid,
  detergent_dispenser: Beaker,
};

const APPLIANCE_GRADIENT: Record<string, string> = {
  refrigerator:
    "from-sky-100 to-blue-200 text-sky-700 dark:from-sky-950/40 dark:to-blue-900/40 dark:text-sky-300",
  dishwasher:
    "from-emerald-100 to-cyan-200 text-emerald-700 dark:from-emerald-950/40 dark:to-cyan-900/40 dark:text-emerald-300",
};


export function ProductCard({ part }: { part: PartCardData }) {
  const price = (part.price_cents / 100).toFixed(2);
  return (
    <article className="overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
      <header className="flex items-center gap-2 bg-ps-blue/5 px-4 py-2 text-[11px] uppercase tracking-wider text-ps-blue">
        <Package size={14} />
        <span>Part</span>
      </header>
      <div className="grid grid-cols-[auto,1fr] gap-3 p-4">
        <PartThumbnail part={part} />
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

function PartThumbnail({ part }: { part: PartCardData }) {
  const [imageFailed, setImageFailed] = useState(false);
  const hasUrl = !!part.image_url && !imageFailed;

  if (hasUrl) {
    return (
      <div className="h-20 w-20 overflow-hidden rounded-lg bg-surface-muted">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={part.image_url}
          alt={part.name}
          loading="lazy"
          onError={() => setImageFailed(true)}
          className="h-full w-full object-cover"
        />
      </div>
    );
  }

  const Icon = PART_TYPE_ICON[part.part_type] ?? Package;
  const gradient =
    APPLIANCE_GRADIENT[part.appliance_type] ??
    "from-slate-100 to-slate-200 text-slate-600 dark:from-slate-800 dark:to-slate-900 dark:text-slate-300";

  return (
    <div
      className={`flex h-20 w-20 items-center justify-center rounded-lg bg-gradient-to-br ${gradient}`}
      aria-label={part.part_type.replace(/_/g, " ")}
    >
      <Icon size={32} strokeWidth={1.6} aria-hidden />
    </div>
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
