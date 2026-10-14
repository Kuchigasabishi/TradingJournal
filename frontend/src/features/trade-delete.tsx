import type { Trade } from "../api/client";
import { useDeleteTrade } from "../api/queries";
import { formatQuantity } from "../lib/money";
import { useFlash } from "../state/providers";
import { ConfirmDialog } from "../ui/feedback";
import { messageOf } from "./common";

/**
 * Asks before deleting a trade, deletes it, and says what happened. Open it by passing the trade; it closes
 * itself through `onClose`. A parent that wants to leave the screen once the trade is gone passes `onDeleted`.
 */
export function DeleteTradeDialog({ trade, onClose, onDeleted }: { trade: Trade | null; onClose: () => void; onDeleted?: (trade: Trade) => void }) {
  const remove = useDeleteTrade();
  const flash = useFlash();

  const confirm = async () => {
    if (trade === null) return;
    try {
      await remove.mutateAsync(trade.id);
      flash.show(`Deleted the ${trade.instrument} trade.`);
      onDeleted?.(trade);
    } catch (error) {
      flash.show(messageOf(error), "error");
    } finally {
      onClose();
    }
  };

  return (
    <ConfirmDialog
      visible={trade !== null}
      title="Delete this trade?"
      message={trade ? `${trade.instrument} ${trade.side}, ${formatQuantity(trade.lot_size)} lots. This cannot be undone.` : ""}
      confirmLabel="Delete trade"
      busy={remove.isPending}
      onConfirm={() => void confirm()}
      onCancel={onClose}
      testID="delete-trade-dialog"
    />
  );
}
