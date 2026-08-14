import { SiteNav } from "@/components/site-nav";
import { Footer } from "@/components/footer";
import { PricingSection } from "@/components/landing/pricing";
import { PricingFaq } from "@/components/landing/pricing-faq";
import { FinalCta } from "@/components/landing/final-cta";

export const metadata = {
  title: "Pricing",
};

export default function PricingPage() {
  return (
    <>
      <SiteNav />
      <main>
        <PricingSection />
        <PricingFaq />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}
