import { useEffect, useState, type FormEvent } from "react";
import { Mail, Phone, User } from "lucide-react";
import { toast } from "sonner";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getProfile, updateProfile, type AuthUser } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function ProfileSection() {
  const auth = useAuth();
  const setAuthUser = auth?.setUser;
  const [profile, setProfile] = useState<AuthUser | null>(auth?.user ?? null);
  const [firstName, setFirstName] = useState(auth?.user.first_name ?? "");
  const [lastName, setLastName] = useState(auth?.user.last_name ?? "");
  const [phone, setPhone] = useState(auth?.user.phone_number ?? "");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getProfile()
      .then(({ profile: current }) => {
        if (!active) return;
        setProfile(current);
        setFirstName(current.first_name);
        setLastName(current.last_name);
        setPhone(current.phone_number ?? "");
        setAuthUser?.(current);
      })
      .catch((cause) => {
        if (active)
          setError(cause instanceof Error ? cause.message : "Could not load your profile.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [setAuthUser]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const { profile: updated } = await updateProfile({
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        phone_number: phone.trim() || null,
      });
      setProfile(updated);
      auth?.setUser(updated);
      toast.success("Profile saved.");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Could not save your profile.";
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <section className="surface p-6 text-sm text-muted-foreground" role="status">
        Loading your profile…
      </section>
    );
  }

  return (
    <section className="surface space-y-6 p-6">
      {profile && (
        <div className="flex items-center gap-4">
          <Avatar className="h-16 w-16 shrink-0">
            <AvatarFallback className="bg-primary-soft text-lg font-semibold text-primary">
              {initials(profile.name) || "GW"}
            </AvatarFallback>
          </Avatar>
          <div>
            <h2 className="text-lg font-semibold">{profile.name}</h2>
            <p className="text-sm text-muted-foreground">{profile.email}</p>
          </div>
        </div>
      )}

      <form className="space-y-6" onSubmit={save}>
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="profile-first-name">First name</Label>
            <div className="relative">
              <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="profile-first-name"
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                className="pl-9"
                required
                maxLength={60}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile-last-name">Last name</Label>
            <Input
              id="profile-last-name"
              value={lastName}
              onChange={(event) => setLastName(event.target.value)}
              maxLength={60}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile-email">Email</Label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="profile-email"
                type="email"
                value={profile?.email ?? ""}
                className="pl-9"
                readOnly
                aria-describedby="profile-email-help"
              />
            </div>
            <p id="profile-email-help" className="text-xs text-muted-foreground">
              Your sign-in email can’t be changed here.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile-phone">Phone number</Label>
            <div className="relative">
              <Phone className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="profile-phone"
                type="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                className="pl-9"
                maxLength={30}
              />
            </div>
          </div>
        </div>
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" disabled={saving || !profile}>
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </form>
    </section>
  );
}
