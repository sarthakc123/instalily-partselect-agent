import { ProviderSwitcher } from "@/components/provider-switcher";

export function Header() {
  return (
    <header className="bg-ps-blue text-ps-blue-fg">
      <div className="mx-auto flex h-14 w-full max-w-3xl items-center justify-between px-4">
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-semibold tracking-tight">
            PartSelect
          </span>
          <span className="text-xs uppercase tracking-wider text-white/70">
            Chat
          </span>
        </div>
        <ProviderSwitcher />
      </div>
      <div className="h-1 bg-ps-orange" aria-hidden />
    </header>
  );
}
