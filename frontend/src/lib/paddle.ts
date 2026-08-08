"use client";

export type BillingPlan = "starter" | "pro" | "scale";

declare global {
  interface Window {
    Paddle?: {
      Initialize: (options: { token: string }) => void;
      Checkout: {
        open: (options: {
          items: { priceId: string; quantity?: number }[];
          customData?: Record<string, unknown>;
          settings?: { displayMode?: string };
        }) => void;
      };
    };
  }
}

const PADDLE_CLIENT_TOKEN = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN;
const PRICE_IDS: Record<BillingPlan, string | undefined> = {
  starter: process.env.NEXT_PUBLIC_PADDLE_STARTER_PRICE_ID,
  pro: process.env.NEXT_PUBLIC_PADDLE_PRO_PRICE_ID,
  scale: process.env.NEXT_PUBLIC_PADDLE_SCALE_PRICE_ID,
};

function loadPaddle(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  return new Promise((resolve) => {
    if (window.Paddle) return resolve(true);
    const script = document.createElement("script");
    script.src = "https://cdn.paddle.com/paddle/v2/paddle.js";
    script.async = true;
    script.onload = () => {
      if (window.Paddle && PADDLE_CLIENT_TOKEN) {
        window.Paddle.Initialize({ token: PADDLE_CLIENT_TOKEN });
      }
      resolve(Boolean(window.Paddle));
    };
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

export async function openCheckout(
  plan: BillingPlan,
  userId: string
): Promise<boolean> {
  const priceId = PRICE_IDS[plan];
  if (!PADDLE_CLIENT_TOKEN || !priceId) return false;
  const loaded = await loadPaddle();
  if (!loaded || !window.Paddle) return false;
  window.Paddle.Checkout.open({
    items: [{ priceId, quantity: 1 }],
    customData: { user_id: userId },
  });
  return true;
}

/** True when the client token and at least one price id are configured. */
export function isPaddleConfigured(): boolean {
  return Boolean(PADDLE_CLIENT_TOKEN && (PRICE_IDS.pro || PRICE_IDS.starter));
}
