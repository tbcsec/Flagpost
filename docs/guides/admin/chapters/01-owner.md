A fresh Flagpost install ships with **no administrator account** — there is
no default password to change, because there is no default login to leak.
The first visit is greeted by the **setup wizard**: **Account** (the owner's
username, optional email and password), **Branding** (platform name, palette
and accent — the logo comes later) and **Options** (public registration open
or closed; daily update checks on or off). Until it completes, public
registration stays closed and the site reports itself as unconfigured.

!!! note "Setup runs once"
    The wizard never reopens on a configured install — not even if the site
    is somehow left with no administrator — because an open wizard on a
    live site would be an anonymous takeover. Flagpost instead refuses to
    ban, delete or demote the *last* active Administrator. Keep two.

Your administrator account is global: it carries the site-wide permissions
this guide covers — users, roles, sign-in options, site settings, the judge
and instance infrastructure, and every competition on the instance.
Day-to-day *event* work (authoring challenges, running a competition) is the
Judge guide; many admins wear both hats, but the surfaces are separate. Both
guides are in the app under **User guides** in the top bar.

## Your home: the Admin area

![The admin dashboard](assets/overview.png)
*Admin → Dashboard: the site at a glance — competitions, accounts, teams,
challenges, solves and submissions, and a health table per competition.*

The **Admin** section of the sidebar gathers the global surfaces, each with
a chapter or section below: Dashboard, Skills, Competitions, Users, Roles,
Event log, Automations, Pages, Marketplace, and Site settings.

!!! note "Who sees the Admin section"
    Anyone holding a global grant that unlocks one of its pages — and they
    see only the pages they can open. A colleague delegated just the event
    log gets an Admin section with just the Event log in it.

## Staying current

When a newer release exists, a dismissible banner tells administrators
*Flagpost X is available — you're running Y*, with **How to update**; the
Update checks card in Site settings shows the running version and the last
check, and the footer's **Changelog** lists what each release shipped.

!!! tip "Delegate with roles, not shared logins"
    Resist the shared admin account. Chapter 3 shows how to grant a
    colleague exactly the site-wide permissions they need under their own
    identity — the event log is only as useful as the names in it.
