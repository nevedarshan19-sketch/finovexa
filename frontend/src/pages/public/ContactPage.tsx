import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  BriefcaseBusiness,
  CheckCircle2,
  Code2,
  Headphones,
  LockKeyhole,
  Mail,
  MessageSquare,
  Phone,
  Send,
} from "lucide-react";
import { getErrorMessage, post } from "../../lib/api";
import type { ContactResponse } from "../../lib/publicTypes";
import {
  Eyebrow,
  GlassCard,
  GradientText,
  Pill,
  PublicCheckbox,
  PublicField,
  PublicInput,
  PublicSelect,
  PublicTextarea,
  Reveal,
  Section,
} from "../../components/public/PublicUI";

const CATEGORIES = [
  { value: "general", label: "General enquiry", icon: MessageSquare },
  { value: "support", label: "Product support", icon: Headphones },
  { value: "partnership", label: "Business partnership", icon: BriefcaseBusiness },
  { value: "developer", label: "Developer contact", icon: Code2 },
] as const;

type Category = (typeof CATEGORIES)[number]["value"];

export function ContactPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [phone, setPhone] = useState("");
  const [category, setCategory] = useState<Category>("general");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [honeypot, setHoneypot] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ContactResponse | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!consent) {
      setError("Please confirm the consent statement before sending your message.");
      return;
    }
    if (message.trim().length < 20) {
      setError("Please write at least 20 characters so the team can help.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await post<ContactResponse>(
        "/public/contact",
        {
          name: name.trim(),
          email: email.trim(),
          organisation: organisation.trim() || undefined,
          phone: phone.trim() || undefined,
          category,
          subject: subject.trim(),
          message: message.trim(),
          consent,
          website: honeypot || undefined,
        },
        { auth: false },
      );
      setResult(response);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="pb-8">
      <Section className="pb-10 pt-14 sm:pt-20">
        <Reveal>
          <div className="max-w-3xl">
            <Eyebrow icon={Mail}>Contact</Eyebrow>
            <h1 className="mt-5 text-balance text-[38px] font-semibold leading-[1.06] tracking-tight text-white sm:text-[50px]">
              Talk to the <GradientText>FINOVEXA team</GradientText>
            </h1>
            <p className="mt-4 text-sm leading-relaxed text-slate-400 sm:text-[15px]">
              Questions about the platform, a partnership, accounting services or developer access — send a
              message and it will be recorded for the platform team to review.
            </p>
          </div>
        </Reveal>
      </Section>

      <Section className="pb-16">
        <div className="grid gap-5 lg:grid-cols-[1fr_1.25fr]">
          <div className="space-y-4">
            <Reveal>
              <GlassCard className="p-6">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Official contact details
                </p>
                <p className="mt-3 text-[11.5px] leading-relaxed text-slate-400">
                  Official email and phone details are not published here. The form below is the
                  supported way to reach the platform team.
                </p>
                <div className="mt-4 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3.5 py-3 text-[10.5px] leading-relaxed text-slate-500">
                  Developer credentials are provisioned server-side and are never shared through this
                  form. Use the developer console for authorised access.
                </div>
              </GlassCard>
            </Reveal>

            <Reveal delay={80}>
              <GlassCard className="p-6">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Where to go
                </p>
                <div className="mt-3 space-y-2">
                  {CATEGORIES.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setCategory(item.value)}
                      className={`flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left text-[12px] transition ${
                        category === item.value
                          ? "border-brand-400/40 bg-brand-500/10 text-white"
                          : "border-white/[0.07] bg-white/[0.02] text-slate-300 hover:border-white/15"
                      }`}
                    >
                      <item.icon className="h-3.5 w-3.5 text-brand-300" aria-hidden />
                      {item.label}
                      <span className="ml-auto text-[10px] text-slate-500">
                        {item.value === "general"
                          ? "Team"
                          : item.value === "support"
                            ? "Product"
                            : item.value === "partnership"
                              ? "Business"
                              : "Console"}
                      </span>
                    </button>
                  ))}
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link
                    to="/developer/login"
                    className="rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 transition hover:bg-white/5"
                  >
                    Developer console
                  </Link>
                </div>
              </GlassCard>
            </Reveal>
          </div>

          <Reveal delay={120}>
            <GlassCard className="p-6 sm:p-8">
              {result ? (
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
                    <CheckCircle2 className="h-5 w-5" aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold text-white">Message recorded</h2>
                    <p className="mt-1 text-xs leading-relaxed text-slate-400">{result.message}</p>
                    <p className="mt-2 inline-flex rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 font-mono text-[11px] text-slate-300">
                      Reference {result.reference}
                    </p>
                    <p className="mt-3 text-[11px] leading-relaxed text-slate-500">{result.note}</p>
                    <button
                      type="button"
                      onClick={() => {
                        setResult(null);
                        setSubject("");
                        setMessage("");
                        setConsent(false);
                      }}
                      className="mt-4 rounded-lg border border-white/15 px-3 py-1.5 text-[11px] font-semibold text-slate-200 transition hover:bg-white/5"
                    >
                      Send another message
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="text-sm font-semibold text-white">Send a message</h2>
                    <Pill tone="slate">Stored securely</Pill>
                  </div>
                  <form onSubmit={submit} className="mt-4 space-y-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <PublicField label="Name" htmlFor="contact-name" required>
                        <PublicInput
                          id="contact-name"
                          value={name}
                          onChange={(event) => setName(event.target.value)}
                          required
                          minLength={2}
                          maxLength={120}
                          autoComplete="name"
                        />
                      </PublicField>
                      <PublicField label="Email" htmlFor="contact-email" required>
                        <PublicInput
                          id="contact-email"
                          type="email"
                          value={email}
                          onChange={(event) => setEmail(event.target.value)}
                          required
                          autoComplete="email"
                        />
                      </PublicField>
                      <PublicField label="Organisation" htmlFor="contact-organisation" hint="Optional">
                        <PublicInput
                          id="contact-organisation"
                          value={organisation}
                          onChange={(event) => setOrganisation(event.target.value)}
                          maxLength={160}
                          autoComplete="organization"
                        />
                      </PublicField>
                      <PublicField label="Phone" htmlFor="contact-phone" hint="Optional">
                        <PublicInput
                          id="contact-phone"
                          type="tel"
                          value={phone}
                          onChange={(event) => setPhone(event.target.value)}
                          maxLength={40}
                          autoComplete="tel"
                        />
                      </PublicField>
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <PublicField label="Enquiry category" htmlFor="contact-category" required>
                        <PublicSelect
                          id="contact-category"
                          value={category}
                          onChange={(event) => setCategory(event.target.value as Category)}
                        >
                          {CATEGORIES.map((item) => (
                            <option key={item.value} value={item.value}>
                              {item.label}
                            </option>
                          ))}
                        </PublicSelect>
                      </PublicField>
                      <PublicField label="Subject" htmlFor="contact-subject" required>
                        <PublicInput
                          id="contact-subject"
                          value={subject}
                          onChange={(event) => setSubject(event.target.value)}
                          required
                          minLength={3}
                          maxLength={160}
                          placeholder="Short summary"
                        />
                      </PublicField>
                    </div>
                    <PublicField
                      label="Message"
                      htmlFor="contact-message"
                      required
                      hint="Minimum 20 characters. Do not include passwords, API keys or card details."
                    >
                      <PublicTextarea
                        id="contact-message"
                        value={message}
                        onChange={(event) => setMessage(event.target.value)}
                        required
                        minLength={20}
                        maxLength={4000}
                        placeholder="Tell us what you need help with."
                      />
                    </PublicField>

                    <div className="hidden" aria-hidden>
                      <label htmlFor="contact-website">Website</label>
                      <input
                        id="contact-website"
                        type="text"
                        tabIndex={-1}
                        autoComplete="off"
                        value={honeypot}
                        onChange={(event) => setHoneypot(event.target.value)}
                      />
                    </div>

                    <PublicCheckbox
                      checked={consent}
                      onChange={setConsent}
                      label="I consent to FINOVEXA storing this message and contact details so the platform team can respond. I understand no automatic email is sent."
                    />

                    {error && (
                      <p className="rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-[11.5px] text-rose-200">
                        {error}
                      </p>
                    )}

                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="flex items-center gap-1.5 text-[10.5px] text-slate-500">
                        <LockKeyhole className="h-3 w-3" aria-hidden /> Only the platform team can review
                        this message.
                      </p>
                      <button
                        type="submit"
                        disabled={submitting}
                        className="inline-flex items-center justify-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-5 py-2.5 text-xs font-semibold text-white shadow-[0_16px_36px_-18px_rgba(36,120,240,0.95)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        <Send className="h-3.5 w-3.5" aria-hidden />
                        {submitting ? "Sending…" : "Send message"}
                      </button>
                    </div>
                  </form>
                </>
              )}
            </GlassCard>
          </Reveal>
        </div>
      </Section>
    </div>
  );
}
