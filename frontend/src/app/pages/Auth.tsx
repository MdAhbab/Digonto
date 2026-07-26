import { useState } from "react";
import { useNavigate, useLocation } from "react-router";
import { Mail, ArrowRight } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useAuth } from "../lib/auth";
import { motion, AnimatePresence } from "motion/react";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "../components/ui/input-otp";

export function Auth() {
  const { t } = useI18n();
  const nav = useNavigate();
  const loc = useLocation();
  const { login } = useAuth();
  const from = (loc.state as { from?: string } | null)?.from ?? "/planner";
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");

  return (
    <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-md flex-col justify-center px-6 py-20">
      {/* letterpressed card */}
      <div className="rounded-[4px] border border-[var(--hairline)] bg-card p-8 md:p-10">
        <div className="mb-8 text-center">
          <div className="font-serif text-3xl">{t("brand.name")}</div>
          <div className="mt-1 font-mono text-[0.62rem] uppercase tracking-[0.28em] text-muted-foreground">est. Dhaka</div>
        </div>

        <AnimatePresence mode="wait">
          {step === "email" ? (
            <motion.form
              key="email"
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 12 }}
              onSubmit={(e) => { e.preventDefault(); if (email.includes("@")) setStep("code"); }}
            >
              <h1 className="font-serif text-2xl">{t("auth.title")}</h1>
              <p className="mt-2 text-sm text-muted-foreground">{t("auth.sub")}</p>
              <label className="mt-8 block">
                <span className="mb-2 block font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">{t("auth.email")}</span>
                <div className="relative">
                  <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="focus-ring h-12 w-full rounded-[3px] border border-border bg-input-background pl-9 pr-3 text-sm outline-none"
                  />
                </div>
              </label>
              <button className="focus-ring mt-6 inline-flex h-12 w-full items-center justify-center gap-2 rounded-[3px] bg-primary text-primary-foreground transition-opacity hover:opacity-90">
                {t("auth.sendcode")} <ArrowRight className="size-4" />
              </button>
            </motion.form>
          ) : (
            <motion.form
              key="code"
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -12 }}
              onSubmit={(e) => { e.preventDefault(); if (code.length < 6) return; login(email); nav(from, { replace: true }); }}
            >
              <h1 className="font-serif text-2xl">{t("auth.title")}</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                {t("auth.codesent")} <span className="text-foreground">{email}</span>
              </p>
              <div className="mt-8 flex justify-center">
                <InputOTP maxLength={6} value={code} onChange={setCode}>
                  <InputOTPGroup>
                    {[0, 1, 2, 3, 4, 5].map((i) => (
                      <InputOTPSlot key={i} index={i} className="h-12 w-11 border-border text-lg" />
                    ))}
                  </InputOTPGroup>
                </InputOTP>
              </div>
              <button className="focus-ring mt-8 inline-flex h-12 w-full items-center justify-center gap-2 rounded-[3px] bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50" disabled={code.length < 6}>
                {t("auth.verify")} <ArrowRight className="size-4" />
              </button>
              <button type="button" onClick={() => setStep("email")} className="focus-ring mt-4 block w-full text-center text-xs text-muted-foreground hover:text-foreground">
                {t("auth.resend")}
              </button>
            </motion.form>
          )}
        </AnimatePresence>
      </div>
      <p className="mt-6 text-center font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">{t("common.free")}</p>
    </div>
  );
}
