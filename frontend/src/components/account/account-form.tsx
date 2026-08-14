"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, KeyRound, Loader2, Trash2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AccountForm({ email }: { email: string }) {
  const router = useRouter();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pwLoading, setPwLoading] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSuccess, setPwSuccess] = useState(false);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [delLoading, setDelLoading] = useState(false);
  const [delError, setDelError] = useState<string | null>(null);

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwError(null);
    setPwSuccess(false);
    if (password.length < 6) {
      setPwError("New password must be at least 6 characters.");
      return;
    }
    if (password !== confirm) {
      setPwError("Passwords do not match.");
      return;
    }
    setPwLoading(true);
    try {
      const res = await fetch("/api/account/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setPwError(data.detail ?? "Could not change the password.");
      } else {
        setPwSuccess(true);
        setPassword("");
        setConfirm("");
      }
    } catch {
      setPwError("Network error — please try again.");
    } finally {
      setPwLoading(false);
    }
  };

  const deleteAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (deleteConfirm !== email) {
      setDelError("Please type your email address to confirm.");
      return;
    }
    setDelLoading(true);
    setDelError(null);
    try {
      const res = await fetch("/api/account/delete", { method: "POST" });
      if (res.ok) {
        router.push("/");
        router.refresh();
      } else {
        const data = await res.json().catch(() => ({}));
        setDelError(data.detail ?? "Could not delete the account.");
        setDelLoading(false);
      }
    } catch {
      setDelError("Network error — please try again.");
      setDelLoading(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" /> Change password
          </CardTitle>
          <CardDescription>
            Keep your account secure. You'll use the new password next time
            you sign in.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={changePassword} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="new-password">New password</Label>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                placeholder="At least 6 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={6}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="confirm-password">Confirm new password</Label>
              <Input
                id="confirm-password"
                type="password"
                autoComplete="new-password"
                placeholder="Repeat the new password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                minLength={6}
                required
              />
            </div>
            {pwError && <p className="text-sm text-[var(--danger-fg)]">{pwError}</p>}
            {pwSuccess && (
              <p className="text-sm text-foreground">Password updated.</p>
            )}
            <Button type="submit" disabled={pwLoading}>
              {pwLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              Update password
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="border-[var(--danger-border)]">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-[var(--danger-fg)]">
            <AlertTriangle className="h-4 w-4" /> Delete account
          </CardTitle>
          <CardDescription>
            Permanently removes your profile, all reports, uploads and stored
            files. This cannot be undone.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!deleteOpen ? (
            <Button variant="outline" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="h-4 w-4" /> Delete account…
            </Button>
          ) : (
            <form onSubmit={deleteAccount} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="delete-confirm">
                  Type <span className="font-medium text-foreground">{email}</span> to
                  confirm
                </Label>
                <Input
                  id="delete-confirm"
                  type="text"
                  autoComplete="off"
                  value={deleteConfirm}
                  onChange={(e) => setDeleteConfirm(e.target.value)}
                  placeholder={email}
                />
              </div>
              {delError && <p className="text-sm text-[var(--danger-fg)]">{delError}</p>}
              <div className="flex gap-2">
                <Button
                  type="submit"
                  variant="outline"
                  disabled={delLoading || deleteConfirm !== email}
                  className="text-[var(--danger-fg)]"
                >
                  {delLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                  Permanently delete
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setDeleteOpen(false);
                    setDeleteConfirm("");
                    setDelError(null);
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
