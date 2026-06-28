import { Camera } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface QrScannerViewProps {
  onScan?: (token: string) => void;
  disabled?: boolean;
}

/** Student QR scanner placeholder — camera viewfinder per ui-ux §2.1 */
export function QrScannerView({ onScan, disabled }: QrScannerViewProps) {
  return (
    <div
      data-testid="qr-scanner-view"
      className="flex flex-col items-center gap-4"
    >
      <div
        className="flex aspect-square w-full max-w-sm items-center justify-center rounded-lg border-2 border-dashed border-primary-500 bg-surface-raised"
        aria-hidden="true"
      >
        <Camera className="h-16 w-16 text-text-secondary" />
      </div>
      <p className="text-body text-text-secondary">Đưa mã QR vào khung</p>
      <Button
        type="button"
        disabled={disabled}
        onClick={() => onScan?.("demo-token-id")}
        aria-label="Quét mã QR"
      >
        Quét mã QR
      </Button>
    </div>
  );
}
