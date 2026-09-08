import { useNavigate } from "react-router-dom";
import { FormAlert } from "@/components/ui/form-alert";
import { titleFromMessage } from "@/features/conversations/api";
import { useCreateConversation } from "@/features/conversations/queries";
import { StartPane } from "@/features/messages/start-pane";

/**
 * `/app` — where a new conversation begins.
 *
 * This used to ask for a title first, on its own screen, with the thread one
 * click further on. That was a form standing between the user and the thing
 * they came to do, for a field that is now filled in from the first message
 * anyway. So the prompt is the whole page.
 *
 * **Nothing is created until something is sent.** Creating the conversation on
 * mount would leave an empty row behind every time this page is opened and
 * abandoned, and the sidebar would fill with untouched Untitleds. The order is
 * create, then hand the text to the conversation that now exists.
 */
export default function NewConversationPage() {
  const navigate = useNavigate();
  const create = useCreateConversation();

  function onSend(text: string) {
    // Named in the create call rather than renamed afterwards. The rename path
    // exists for a conversation that already exists and is still called
    // Untitled; here the first message is already in hand, so using it saves a
    // request and, more visibly, stops the header rendering 'Untitled' for a
    // moment before correcting itself.
    create.mutate(
      { title: titleFromMessage(text) },
      {
        onSuccess: (conversation) =>
          // The text rides along in history state rather than being posted
          // from here. Posting it here would mean streaming the reply into a
          // component that is about to unmount, which aborts it.
          navigate(`/app/c/${conversation.id}`, {
            state: { firstMessage: text },
          }),
      },
    );
  }

  return (
    <StartPane
      onSend={onSend}
      disabled={create.isPending}
      error={
        create.error ? <FormAlert>{create.error.message}</FormAlert> : null
      }
    />
  );
}
