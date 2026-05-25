import { ChatPanel } from "@/components/chat-panel";

export default function Home() {
  return (
    <div className="flex flex-1 flex-col gap-4">
      <section className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-foreground">
          Refrigerator and dishwasher parts help
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Ask about a part number, check whether a part fits your model, or
          describe a problem your appliance is having. The agent will look
          things up in our catalog before answering.
        </p>
        <ul className="mt-4 grid grid-cols-1 gap-2 text-sm text-muted-foreground sm:grid-cols-2">
          <li className="rounded-lg bg-surface-muted px-3 py-2">
            &ldquo;How can I install part number PS11752778?&rdquo;
          </li>
          <li className="rounded-lg bg-surface-muted px-3 py-2">
            &ldquo;Is this part compatible with my WDT780SAEM1 model?&rdquo;
          </li>
          <li className="rounded-lg bg-surface-muted px-3 py-2">
            &ldquo;My Whirlpool fridge ice maker is not working.&rdquo;
          </li>
          <li className="rounded-lg bg-surface-muted px-3 py-2">
            &ldquo;The dishwasher will not drain. Help.&rdquo;
          </li>
        </ul>
      </section>

      <ChatPanel />
    </div>
  );
}
