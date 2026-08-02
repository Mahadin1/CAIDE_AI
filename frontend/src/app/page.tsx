import { SiteNav } from "@/components/site-nav";
import { Footer } from "@/components/footer";
import { Hero } from "@/components/landing/hero";
import { HowItWorks } from "@/components/landing/how-it-works";
import { Features } from "@/components/landing/features";
import { PricingSection } from "@/components/landing/pricing";
import { FinalCta } from "@/components/landing/final-cta";

export default function Home() {
  return (
    <>
      <SiteNav />
      <main>
        <Hero />
        <HowItWorks />
        <Features />
        <PricingSection />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}
