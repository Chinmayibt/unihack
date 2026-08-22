import Link from "next/link";

export default function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="shell">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4 fade-up">
        <Link href="/">
          <h1 className="brand text-3xl text-[var(--ink)] md:text-4xl">ALETHEIA</h1>
          <p className="mt-1 max-w-md text-sm text-[var(--muted)]">
            The Truth Layer for Industrial Product Data
          </p>
        </Link>
        <nav className="flex flex-wrap gap-2">
          <Link className="btn btn-ghost" href="/">
            Home
          </Link>
          <Link className="btn btn-ghost" href="/dashboard">
            Dashboard
          </Link>
          <Link className="btn btn-ghost" href="/upload">
            Intake
          </Link>
          <Link className="btn btn-primary" href="/review">
            Review queue
          </Link>
        </nav>
      </header>
      {children}
    </div>
  );
}
