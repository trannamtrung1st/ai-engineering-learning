import { Link } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { SessionStatusBadge } from "../../components/ui/StatusBadge";
import { ContentSection } from "../../components/layout/ContentSection";
import { MobileFlowContainer } from "../../components/layout/MobileFlowContainer";
import { Card } from "../../components/ui/Card";
import styles from "./DesignSystemPage.module.css";

export function DesignSystemPage() {
  return (
    <MobileFlowContainer
      title="Attendly Design System"
      subtitle="Tokenized Neobrutalism shell — FR-14 · NFR-14 · NFR-15 foundations"
    >
      <ContentSection title="Primitives">
        <Card>
          <div className={styles.buttonRow}>
            <Button>Brand</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="danger">Danger</Button>
            <Button variant="ghost">Ghost</Button>
            <Button disabled>Disabled</Button>
          </div>
        </Card>
        <FeedbackAlert variant="success" title="Thành công">
          Tokenized alerts với viền 2px và bóng cứng.
        </FeedbackAlert>
        <SessionStatusBadge state="Open" />
      </ContentSection>

      <ContentSection title="Route shells">
        <div className={styles.links}>
          <Link className={styles.routeLink} to="/check-in?outcome=expired-qr">
            PG-02 · Mobile check-in outcomes
          </Link>
          <Link className={styles.routeLink} to="/login?returnUrl=%2Fcheck-in%3Ftoken%3Ddemo">
            PG-01 · Login gate với return URL
          </Link>
          <Link className={styles.routeLink} to="/lecturer/sessions/demo-open">
            PG-05 · QrDisplayPanel (Open)
          </Link>
          <Link className={styles.routeLink} to="/lecturer/sessions/demo-closed">
            PG-05 · QrDisplayPanel (Closed)
          </Link>
        </div>
      </ContentSection>
    </MobileFlowContainer>
  );
}