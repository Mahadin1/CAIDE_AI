"use client";

import { useEffect, useState } from "react";
import { Loader2, Moon, Save, Sun, User } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ProfileInfo({
  initialName,
  email,
}: {
  initialName: string | null;
  email: string;
}) {
  const [name, setName] = useState(initialName ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [light, setLight] = useState(false);

  useEffect(() => {
    setLight(document.documentElement.classList.contains("light"));
  }, []);

  const saveName = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const supabase = createClient();
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setError("Session expired — please sign in again.");
        return;
      }
      const { error: upErr } = await supabase
        .from("profiles")
        .update({ name: name.trim() || null })
        .eq("id", user.id);
      if (upErr) {
        setError(upErr.message);
      } else {
        setSaved(true);
      }
    } catch {
      setError("Network error — please try again.");
    } finally {
      setSaving(false);
    }
  };

  const toggleTheme = () => {
    const next = !light;
    setLight(next);
    document.documentElement.classList.toggle("light", next);
    try {
      localStorage.setItem("datascope-theme", next ? "light" : "dark");
      localStorage.setItem("datascope-theme-set", next ? "light" : "dark");
    } catch {
      // storage unavailable
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <User className="h-4 w-4" /> Personal information
          </CardTitle>
          <CardDescription>
            Your name is shown in the header of the dashboard.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={saveName} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="profile-name">Name</Label>
              <Input
                id="profile-name"
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setSaved(false);
                }}
                placeholder="Your name"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input type="email" value={email} disabled />
              <p className="text-xs text-muted">
                Your email is your sign-in and can't be changed here.
              </p>
            </div>
            {error && <p className="text-sm text-[#f87171]">{error}</p>}
            {saved && <p className="text-sm text-foreground">Saved.</p>}
            <Button type="submit" disabled={saving}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              <Save className="h-4 w-4" /> Save changes
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>
            Switch between the dark and light theme. Your choice is remembered
            on this device.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between rounded-md border border-border bg-surface p-4">
            <div>
              <p className="text-sm font-medium">
                {light ? "Light theme" : "Dark theme"}
              </p>
              <p className="text-xs text-muted">
                {light
                  ? "Clean white surfaces with the indigo accent."
                  : "Near-black surfaces with the indigo accent."}
              </p>
            </div>
            <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label="Toggle theme">
              {light ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
