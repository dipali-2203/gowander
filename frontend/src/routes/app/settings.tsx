import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Link2, Unlink } from "lucide-react";
import { ProfileSection } from "@/components/layout/ProfileSection";
import { PageHeader } from "@/components/travel/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTheme } from "@/hooks/use-theme";
import { destinations } from "@/data/destinations";
import {
  currentUser,
  disconnectGoogleAccount,
  startGoogleAccountLink,
  type AuthUser,
} from "@/lib/api";

export const Route = createFileRoute("/app/settings")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "Profile & Settings · GoWander" },
      {
        name: "description",
        content:
          "Manage your profile, travel preferences, bookmarks, theme, notifications and account security.",
      },
      { property: "og:title", content: "Profile & Settings · GoWander" },
      {
        property: "og:description",
        content: "Personalise how GoWander plans your journeys.",
      },
    ],
  }),
  component: Settings,
});

const prefs = ["Heritage", "Food", "Mountains", "Slow travel", "Photography"];

function Settings() {
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [account, setAccount] = useState<AuthUser | null>(null);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [activeTab, setActiveTab] = useState("profile");

  useEffect(() => {
    let active = true;
    currentUser()
      .then(({ user }) => {
        if (active) setAccount(user);
      })
      .catch(() => {
        if (active) void navigate({ to: "/login", replace: true });
      });

    const url = new URL(window.location.href);
    const linkStatus = url.searchParams.get("google_link");
    if (url.searchParams.get("tab") === "account") setActiveTab("account");
    if (linkStatus === "connected") toast.success("Google account connected.");
    if (linkStatus === "error")
      toast.error(
        "Google account could not be connected. Check that it uses the same email as this account.",
      );
    if (linkStatus) {
      url.searchParams.delete("google_link");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    }

    return () => {
      active = false;
    };
  }, [navigate]);

  async function connectGoogle() {
    setGoogleBusy(true);
    try {
      const { authorization_url } = await startGoogleAccountLink();
      window.location.assign(authorization_url);
    } catch (cause) {
      const message =
        cause instanceof Error ? cause.message : "Could not start Google account linking.";
      if (/authentication required|session expired/i.test(message)) {
        await navigate({ to: "/login", replace: true });
        return;
      }
      toast.error(message);
      setGoogleBusy(false);
    }
  }

  async function disconnectGoogle() {
    setGoogleBusy(true);
    try {
      await disconnectGoogleAccount();
      const { user } = await currentUser();
      setAccount(user);
      toast.success("Google account disconnected.");
    } catch (cause) {
      const message =
        cause instanceof Error ? cause.message : "Could not disconnect Google account.";
      if (/authentication required|session expired/i.test(message)) {
        await navigate({ to: "/login", replace: true });
        return;
      }
      toast.error(message);
    } finally {
      setGoogleBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader title="Profile & settings" description="Tune how the AI plans for you." />

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="bookmarks">Bookmarks</TabsTrigger>
          <TabsTrigger value="account">Account</TabsTrigger>
        </TabsList>

        <TabsContent value="profile" className="mt-4">
          <ProfileSection />
        </TabsContent>

        <TabsContent value="preferences" className="mt-4 space-y-4">
          <section className="surface space-y-4 p-6">
            <h2 className="font-semibold">Travel preferences</h2>
            <div className="flex flex-wrap gap-2">
              {prefs.map((p) => (
                <Badge key={p} variant="secondary" className="px-3 py-1.5">
                  {p}
                </Badge>
              ))}
            </div>
          </section>
          <section className="surface space-y-4 p-6">
            <h2 className="font-semibold">Appearance & notifications</h2>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="dark">Dark mode</Label>
              <Switch id="dark" checked={theme === "dark"} onCheckedChange={toggle} />
            </div>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="deals">Price drop alerts</Label>
              <Switch id="deals" defaultChecked />
            </div>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="weekly">Weekly destination digest</Label>
              <Switch id="weekly" />
            </div>
          </section>
        </TabsContent>

        <TabsContent value="bookmarks" className="mt-4">
          <section className="surface p-6">
            <h2 className="font-semibold">Bookmarked destinations</h2>
            <ul className="mt-4 grid gap-3 sm:grid-cols-2">
              {destinations.slice(0, 6).map((d) => (
                <li
                  key={d.id}
                  className="flex items-center gap-3 rounded-xl border border-border p-3"
                >
                  <img
                    src={d.image}
                    alt={d.name}
                    loading="lazy"
                    className="h-12 w-12 shrink-0 rounded-lg object-cover"
                  />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{d.name}</p>
                    <p className="truncate text-xs text-muted-foreground">{d.state}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </TabsContent>

        <TabsContent value="account" className="mt-4 space-y-4">
          <section className="surface space-y-4 p-6">
            <div>
              <h2 className="font-semibold">Connected accounts</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Connect Google to sign in with either Google or your existing account credentials.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border p-4">
              <div className="flex items-start gap-3">
                <Link2 className="mt-0.5 h-5 w-5 text-primary" aria-hidden="true" />
                <div>
                  <p className="font-medium">Google account</p>
                  <p className="text-sm text-muted-foreground">
                    {account?.google_connected
                      ? `Connected${account.google_email ? ` as ${account.google_email}` : ""}`
                      : "Not connected"}
                  </p>
                </div>
              </div>
              {account?.google_connected ? (
                <Button
                  variant="outline"
                  onClick={disconnectGoogle}
                  disabled={googleBusy || !account.password_login_enabled}
                >
                  <Unlink className="mr-2 h-4 w-4" />
                  {googleBusy ? "Please wait…" : "Disconnect Google Account"}
                </Button>
              ) : (
                <Button onClick={connectGoogle} disabled={googleBusy || !account}>
                  <Link2 className="mr-2 h-4 w-4" />
                  {googleBusy ? "Please wait…" : "Connect Google Account"}
                </Button>
              )}
            </div>
            {account?.google_connected && !account.password_login_enabled && (
              <p className="text-sm text-muted-foreground">
                Set a password through password reset before disconnecting Google, so you keep
                access to your account.
              </p>
            )}
          </section>
          <section className="surface space-y-4 p-6">
            <h2 className="font-semibold">Security</h2>
            <div className="space-y-2">
              <Label htmlFor="pwd">Change password</Label>
              <Input id="pwd" type="password" placeholder="New password" />
            </div>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="2fa">Two-factor authentication</Label>
              <Switch id="2fa" defaultChecked />
            </div>
            <Button onClick={() => toast.success("Security settings updated")}>Update</Button>
          </section>
          <section className="surface space-y-3 p-6">
            <h2 className="font-semibold">Danger zone</h2>
            <p className="text-sm text-muted-foreground">
              Deleting your account removes every saved itinerary permanently.
            </p>
            <Button variant="destructive" onClick={() => toast.error("Demo only")}>
              Delete account
            </Button>
          </section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
