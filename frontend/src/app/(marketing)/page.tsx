import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "ALETHEIA — The Truth Layer for Industrial Product Data",
  description:
    "ALETHEIA grounds industrial catalog attributes in manufacturer evidence, taxonomy, validation, and human review.",
};

export default function LandingPage() {
  return (
    <main className="landing">
      <header className="landing-top">
        <Link className="brand landing-top__mark" href="/">
          ALETHEIA
        </Link>
        <nav className="landing-top__nav">
          <a href="#problem">Problem</a>
          <a href="#pipeline">Pipeline</a>
          <a href="#review">Review</a>
          <Link href="/dashboard">Dashboard</Link>
          <Link className="btn btn-primary" href="/upload">
            Start intake
          </Link>
        </nav>
      </header>

      <section className="landing-hero">
        <div
          aria-hidden
          className="landing-hero__media"
          style={{
            backgroundImage:
              "url(https://images.unsplash.com/photo-1504917595217-d4dc5ebe6122?auto=format&fit=crop&w=2400&q=80)",
          }}
        />
        <div className="landing-hero__shade" aria-hidden />
        <div className="landing-hero__content">
          <h1 className="brand landing-title">ALETHEIA</h1>
          <p className="landing-tagline">
            The Truth Layer for Industrial Product Data
          </p>
          <p className="landing-lede">
            Turn messy catalog rows into evidence-backed attributes — classified,
            validated, and ready for human sign-off.
          </p>
          <div className="landing-cta">
            <Link className="btn btn-primary" href="/upload">
              Start intake
            </Link>
            <Link className="btn btn-on-dark" href="/dashboard">
              View live jobs
            </Link>
          </div>
        </div>
      </section>

      <section className="landing-section shell" id="problem">
        <p className="landing-eyebrow">Why it exists</p>
        <h2 className="brand landing-section-title">
          Industrial catalogs drift from the truth
        </h2>
        <p className="landing-section-copy">
          Distributor feeds mix brands, invent LOV values, and strip units. Specs
          live on manufacturer pages that never make it into the PIM. ALETHEIA
          reconstructs a trustworthy product record before anything ships
          downstream.
        </p>
        <ul className="landing-points">
          <li>
            <strong>Conflicting brands</strong>
            <span>E1, Unilog, and DIB disagree on the same MPN.</span>
          </li>
          <li>
            <strong>Weak classification</strong>
            <span>Free-text categories miss the allowed taxonomy path.</span>
          </li>
          <li>
            <strong>Unsourced attributes</strong>
            <span>Voltage, grit, and material appear with no evidence trail.</span>
          </li>
        </ul>
      </section>

      <section className="landing-band" id="truth">
        <div className="shell landing-band__inner">
          <p className="landing-eyebrow landing-eyebrow--light">What ALETHEIA is</p>
          <h2 className="brand landing-section-title landing-section-title--light">
            A truth layer, not another scraper
          </h2>
          <p className="landing-section-copy landing-section-copy--light">
            Every enriched field is tied to manufacturer research, retrieved
            document chunks, LOV/UOM checks, and — when confidence drops — a human
            review queue. Aletheia (ἀλήθεια) means truth that is uncovered, not
            invented.
          </p>
        </div>
      </section>

      <section className="landing-section shell" id="pipeline">
        <p className="landing-eyebrow">Pipeline</p>
        <h2 className="brand landing-section-title">
          From raw MPN to delivery CSV
        </h2>
        <p className="landing-section-copy">
          Eight stages run in order. Nothing is guessed past the evidence you can
          inspect.
        </p>
        <ol className="landing-pipeline">
          <li>
            <span>01</span>
            <div>
              <strong>Understanding</strong>
              <p>Interpret description, brand candidates, and product type signals.</p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <strong>Entity resolution</strong>
              <p>Normalize manufacturer and brand against master data.</p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <strong>Classification</strong>
              <p>Lock to an allowed department → class → fine taxonomy path.</p>
            </div>
          </li>
          <li>
            <span>04</span>
            <div>
              <strong>Research</strong>
              <p>Discover authoritative manufacturer URLs for the MPN.</p>
            </div>
          </li>
          <li>
            <span>05</span>
            <div>
              <strong>RAG indexing</strong>
              <p>Fetch pages, chunk, and index for attribute evidence search.</p>
            </div>
          </li>
          <li>
            <span>06</span>
            <div>
              <strong>Extraction</strong>
              <p>Fill template slots only when evidence or title supports them.</p>
            </div>
          </li>
          <li>
            <span>07</span>
            <div>
              <strong>Normalize &amp; validate</strong>
              <p>Enforce LOV, UOM, and character rules before approval.</p>
            </div>
          </li>
          <li>
            <span>08</span>
            <div>
              <strong>HITL &amp; output</strong>
              <p>Resolve edge cases, then emit the delivery-format CSV.</p>
            </div>
          </li>
        </ol>
      </section>

      <section className="landing-section shell" id="intake">
        <p className="landing-eyebrow">Intake</p>
        <h2 className="brand landing-section-title">Enter data the way you have it</h2>
        <p className="landing-section-copy">
          Batch a distributor file, paste a JSON payload, or enrich one SKU for a
          live demo — same pipeline underneath.
        </p>
        <div className="landing-modes">
          <div>
            <strong>CSV batch</strong>
            <p>UniHack sample schema with MPN, description, and brand columns.</p>
          </div>
          <div>
            <strong>JSON file / paste</strong>
            <p>Single object or array. Friendly keys or CSV column names both work.</p>
          </div>
          <div>
            <strong>Single product</strong>
            <p>Form entry for one MPN when you need a fast, visible run.</p>
          </div>
        </div>
        <Link className="btn btn-primary landing-inline-cta" href="/upload">
          Open intake
        </Link>
      </section>

      <section className="landing-section landing-section--split shell" id="review">
        <p className="landing-eyebrow">Human review</p>
        <h2 className="brand landing-section-title">
          When the model should not decide alone
        </h2>
        <p className="landing-section-copy">
          LOV mismatches, source conflicts, low classification confidence, and
          fetch failures land in a review queue with evidence and allowed values
          beside the AI suggestion. Approve, pick a candidate, mark unknown, or
          reject — then continue to export.
        </p>
        <Link className="btn btn-primary" href="/review">
          Open review queue
        </Link>
      </section>

      <section className="landing-section shell" id="output">
        <p className="landing-eyebrow">Delivery</p>
        <h2 className="brand landing-section-title">Output that matches the brief</h2>
        <p className="landing-section-copy">
          Completed jobs produce the UniHack delivery-format CSV scoped to that
          run — approved and partial rows first, with review items left for the
          human loop. Job metrics track evidence coverage, completeness, and pace.
        </p>
        <Link className="btn btn-ghost" href="/dashboard">
          See job dashboard
        </Link>
      </section>

      <footer className="landing-footer">
        <div className="shell landing-footer__inner">
          <div>
            <p className="brand landing-footer__mark">ALETHEIA</p>
            <p className="landing-footer__tag">
              The Truth Layer for Industrial Product Data
            </p>
          </div>
          <div className="landing-footer__actions">
            <Link className="btn btn-primary" href="/upload">
              Start intake
            </Link>
            <Link className="btn btn-ghost" href="/dashboard">
              Dashboard
            </Link>
          </div>
        </div>
      </footer>
    </main>
  );
}
