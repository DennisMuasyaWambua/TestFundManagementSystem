import { EmptyState, ButtonLink } from "@/components/ui/primitives";

/**
 * A 404 inside the signed-in shell, so the sidebar and the sign-out button stay
 * reachable instead of dropping the user onto a bare page.
 */
export default function NotFound() {
  return (
    <EmptyState
      title="That record does not exist"
      description="The link may be out of date, or the record may belong to a mandate you do not have access to."
      action={<ButtonLink href="/dashboard">Back to the dashboard</ButtonLink>}
    />
  );
}
