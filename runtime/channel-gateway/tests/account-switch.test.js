/**
 * runtime/channel-gateway/tests/account-switch.test.js
 *
 * Canonical Node tests for ADR-0022 D26 pure account switch orchestration.
 * Uses node:test and node:assert only.
 * All test data and fixtures are strictly synthetic.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { ChannelControl } = require('../core/channel-control');
const { AccountRegistry } = require('../core/account-registry');
const { AccountSwitchCoordinator } = require('../core/account-switch');

test('AccountSwitch - 1. registry/control channel mismatch rejected', () => {
  const tgRegistry = new AccountRegistry('telegram');
  const lineControl = new ChannelControl('line');

  assert.throws(
    () => new AccountSwitchCoordinator(tgRegistry, lineControl),
    {
      name: 'Error',
      message: /CHANNEL_CONTROL_MISMATCH/,
    }
  );
});

test('AccountSwitch - 2 to 8. A -> B switch: target active, takeover, fencing token, discard semantics', () => {
  const registry = new AccountRegistry('telegram');
  registry.register({ id: 'syn-bot-a', label: 'Bot A', enabled: true });
  registry.register({ id: 'syn-bot-b', label: 'Bot B', enabled: true });

  const control = new ChannelControl('telegram');
  const coordinator = new AccountSwitchCoordinator(registry, control);

  // Initial activation of Bot A
  coordinator.switchActiveAccount('syn-bot-a', 'syn-agent-old');
  assert.strictEqual(registry.getActive().id, 'syn-bot-a');
  assert.strictEqual(control.currentHolder, 'syn-agent-old');
  assert.strictEqual(control.fencingToken, 1);

  // Set up message scenarios for Bot A and Bot B
  // msg-a1: claimed by syn-agent-old
  control.enqueueMessage({ id: 'msg-a1', receivingAccountId: 'syn-bot-a' });
  control.pollMessages('syn-agent-old', 1);

  // msg-a2: queued for Bot A
  control.enqueueMessage({ id: 'msg-a2', receivingAccountId: 'syn-bot-a' });

  // msg-b1: queued for Bot B
  control.enqueueMessage({ id: 'msg-b1', receivingAccountId: 'syn-bot-b' });

  assert.strictEqual(control.getBacklogCount(), 2); // msg-a2 and msg-b1 are queued

  // Execute A -> B account switch
  const result = coordinator.switchActiveAccount('syn-bot-b', 'syn-agent-new');

  // 2. A -> B: B becomes active
  assert.strictEqual(result.activeAccountId, 'syn-bot-b');
  assert.strictEqual(registry.getActive().id, 'syn-bot-b');
  assert.strictEqual(result.previousActiveAccountId, 'syn-bot-a');
  assert.strictEqual(result.accountChanged, true);

  // 3. A -> B: switch performs takeover
  assert.strictEqual(control.currentHolder, 'syn-agent-new');
  assert.strictEqual(result.holder, 'syn-agent-new');

  // 4. A -> B: fencing token increments
  assert.strictEqual(control.fencingToken, 2);
  assert.strictEqual(result.fencingToken, 2);

  // 5. A claimed message discarded (D9 takeover discard)
  const msgA1 = control.messages.find((m) => m.id === 'msg-a1');
  assert.strictEqual(msgA1.status, 'discarded');
  assert.strictEqual(msgA1.discardReason, 'TAKEOVER');

  // 6. A queued message discarded (D26 account switch discard)
  const msgA2 = control.messages.find((m) => m.id === 'msg-a2');
  assert.strictEqual(msgA2.status, 'discarded');
  assert.strictEqual(msgA2.discardReason, 'ACCOUNT_SWITCH');

  // 7. B queued message preserved for new active account
  const msgB1 = control.messages.find((m) => m.id === 'msg-b1');
  assert.strictEqual(msgB1.status, 'queued');
  assert.strictEqual(control.getBacklogCount(), 1);

  // 8. discardedOldAccountMessages contains both A claimed and A queued messages
  assert.strictEqual(result.discardedOldAccountMessages.length, 2);
  const discardedIds = result.discardedOldAccountMessages.map((m) => m.id);
  assert.strictEqual(discardedIds.includes('msg-a1'), true);
  assert.strictEqual(discardedIds.includes('msg-a2'), true);
  assert.strictEqual(discardedIds.includes('msg-b1'), false);
});

test('AccountSwitch - 9 to 11. same account A -> A: takeover occurs, accountChanged=false, queued preserved', () => {
  const registry = new AccountRegistry('telegram');
  registry.register({ id: 'syn-bot-a', label: 'Bot A', enabled: true });

  const control = new ChannelControl('telegram');
  const coordinator = new AccountSwitchCoordinator(registry, control);

  // Initial activation
  coordinator.switchActiveAccount('syn-bot-a', 'syn-agent-1');
  assert.strictEqual(control.fencingToken, 1);

  // Enqueue queued message for Bot A
  control.enqueueMessage({ id: 'msg-a-queued', receivingAccountId: 'syn-bot-a' });
  assert.strictEqual(control.getBacklogCount(), 1);

  // Same-account selection (A -> A)
  const result = coordinator.switchActiveAccount('syn-bot-a', 'syn-agent-2');

  // 9. same account A -> A: accountChanged=false
  assert.strictEqual(result.accountChanged, false);
  assert.strictEqual(result.previousActiveAccountId, 'syn-bot-a');
  assert.strictEqual(result.activeAccountId, 'syn-bot-a');

  // 10. same account selection: takeover still occurs, fencing token increments
  assert.strictEqual(control.currentHolder, 'syn-agent-2');
  assert.strictEqual(control.fencingToken, 2);
  assert.strictEqual(result.fencingToken, 2);

  // 11. same account: A queued message preserved (takeover only, NOT account migration)
  const msg = control.messages.find((m) => m.id === 'msg-a-queued');
  assert.strictEqual(msg.status, 'queued');
  assert.strictEqual(control.getBacklogCount(), 1);
  assert.strictEqual(result.discardedOldAccountMessages.length, 0);
});

test('AccountSwitch - 12 to 13. no previous active -> target becomes active, queued preserved', () => {
  const registry = new AccountRegistry('telegram');
  registry.register({ id: 'syn-bot-target', label: 'Target Bot', enabled: true });

  const control = new ChannelControl('telegram');
  const coordinator = new AccountSwitchCoordinator(registry, control);

  assert.strictEqual(registry.getActive(), null);

  // Pre-enqueue message for target bot
  control.enqueueMessage({ id: 'msg-target-1', receivingAccountId: 'syn-bot-target' });
  assert.strictEqual(control.getBacklogCount(), 1);

  // First selection
  const result = coordinator.switchActiveAccount('syn-bot-target', 'syn-agent-initial');

  // 12. no previous active -> target becomes active
  assert.strictEqual(result.previousActiveAccountId, null);
  assert.strictEqual(result.activeAccountId, 'syn-bot-target');
  assert.strictEqual(result.accountChanged, true);
  assert.strictEqual(registry.getActive().id, 'syn-bot-target');
  assert.strictEqual(control.currentHolder, 'syn-agent-initial');
  assert.strictEqual(control.fencingToken, 1);

  // 13. no previous active -> target queued preserved
  const msg = control.messages.find((m) => m.id === 'msg-target-1');
  assert.strictEqual(msg.status, 'queued');
  assert.strictEqual(result.discardedOldAccountMessages.length, 0);
  assert.strictEqual(control.getBacklogCount(), 1);
});

test('AccountSwitch - 14. missing target -> zero mutation', () => {
  const registry = new AccountRegistry('telegram');
  registry.register({ id: 'syn-bot-existing', label: 'Existing Bot', enabled: true });

  const control = new ChannelControl('telegram');
  const coordinator = new AccountSwitchCoordinator(registry, control);

  coordinator.switchActiveAccount('syn-bot-existing', 'syn-agent-1');

  control.enqueueMessage({ id: 'msg-steady', receivingAccountId: 'syn-bot-existing' });

  assert.throws(
    () => coordinator.switchActiveAccount('syn-bot-nonexistent', 'syn-agent-2'),
    {
      name: 'Error',
      message: /TARGET_NOT_FOUND/,
    }
  );

  // Verify atomic zero mutation
  assert.strictEqual(registry.getActive().id, 'syn-bot-existing');
  assert.strictEqual(control.currentHolder, 'syn-agent-1');
  assert.strictEqual(control.fencingToken, 1);
  assert.strictEqual(control.messages.find((m) => m.id === 'msg-steady').status, 'queued');
});

test('AccountSwitch - 15. disabled target -> zero mutation', () => {
  const registry = new AccountRegistry('telegram');
  registry.register({ id: 'syn-bot-active', label: 'Active Bot', enabled: true });
  registry.register({ id: 'syn-bot-disabled', label: 'Disabled Bot', enabled: false });

  const control = new ChannelControl('telegram');
  const coordinator = new AccountSwitchCoordinator(registry, control);

  coordinator.switchActiveAccount('syn-bot-active', 'syn-agent-1');
  control.enqueueMessage({ id: 'msg-steady-2', receivingAccountId: 'syn-bot-active' });

  assert.throws(
    () => coordinator.switchActiveAccount('syn-bot-disabled', 'syn-agent-2'),
    {
      name: 'Error',
      message: /TARGET_DISABLED/,
    }
  );

  // Verify atomic zero mutation
  assert.strictEqual(registry.getActive().id, 'syn-bot-active');
  assert.strictEqual(control.currentHolder, 'syn-agent-1');
  assert.strictEqual(control.fencingToken, 1);
  assert.strictEqual(control.messages.find((m) => m.id === 'msg-steady-2').status, 'queued');
});

test('AccountSwitch - 16. wrong holder input -> zero mutation', () => {
  const registry = new AccountRegistry('telegram');
  registry.register({ id: 'syn-bot-1', label: 'Bot 1', enabled: true });
  registry.register({ id: 'syn-bot-2', label: 'Bot 2', enabled: true });

  const control = new ChannelControl('telegram');
  const coordinator = new AccountSwitchCoordinator(registry, control);

  coordinator.switchActiveAccount('syn-bot-1', 'syn-agent-1');

  assert.throws(
    () => coordinator.switchActiveAccount('syn-bot-2', ''),
    {
      name: 'TypeError',
      message: /holderId must be a non-empty string/,
    }
  );
  assert.throws(
    () => coordinator.switchActiveAccount('syn-bot-2', '   '),
    {
      name: 'TypeError',
      message: /holderId must be a non-empty string/,
    }
  );
  assert.throws(
    () => coordinator.switchActiveAccount('syn-bot-2', null),
    {
      name: 'TypeError',
      message: /holderId must be a non-empty string/,
    }
  );

  // Verify atomic zero mutation
  assert.strictEqual(registry.getActive().id, 'syn-bot-1');
  assert.strictEqual(control.currentHolder, 'syn-agent-1');
  assert.strictEqual(control.fencingToken, 1);
});

test('AccountSwitch - 17. post-switch stale old holder cannot authorize reply', () => {
  const registry = new AccountRegistry('telegram');
  registry.register({ id: 'syn-bot-a', label: 'Bot A', enabled: true });
  registry.register({ id: 'syn-bot-b', label: 'Bot B', enabled: true });

  const control = new ChannelControl('telegram');
  const coordinator = new AccountSwitchCoordinator(registry, control);

  // Activate Bot A
  coordinator.switchActiveAccount('syn-bot-a', 'syn-agent-old');

  // Switch to Bot B
  coordinator.switchActiveAccount('syn-bot-b', 'syn-agent-new');

  // Enqueue and claim message under Bot B
  control.enqueueMessage({ id: 'msg-b-post', receivingAccountId: 'syn-bot-b' });
  control.pollMessages('syn-agent-new', 2);

  // Stale holder attempts to authorize reply
  const authStaleHolder = control.authorizeReply(
    'syn-agent-old',
    1,
    'msg-b-post',
    'syn-bot-b'
  );
  assert.strictEqual(authStaleHolder.authorized, false);
  assert.strictEqual(authStaleHolder.reason, 'NOT_CURRENT_HOLDER');

  // Even if stale holder provides the new fencing token, holder mismatch rejects
  const authStaleHolderWithNewToken = control.authorizeReply(
    'syn-agent-old',
    2,
    'msg-b-post',
    'syn-bot-b'
  );
  assert.strictEqual(authStaleHolderWithNewToken.authorized, false);
  assert.strictEqual(authStaleHolderWithNewToken.reason, 'NOT_CURRENT_HOLDER');
});

test('AccountSwitch - 18. post-switch B message can only be replied by receiving account B', () => {
  const registry = new AccountRegistry('telegram');
  registry.register({ id: 'syn-bot-a', label: 'Bot A', enabled: true });
  registry.register({ id: 'syn-bot-b', label: 'Bot B', enabled: true });

  const control = new ChannelControl('telegram');
  const coordinator = new AccountSwitchCoordinator(registry, control);

  // Switch to Bot B
  coordinator.switchActiveAccount('syn-bot-b', 'syn-agent-current');

  // Enqueue and claim message under Bot B
  control.enqueueMessage({ id: 'msg-b-claim', receivingAccountId: 'syn-bot-b' });
  control.pollMessages('syn-agent-current', 1);

  // Cross-account reply attempt by Bot A -> rejected (ACCOUNT_MISMATCH)
  const authMismatch = control.authorizeReply(
    'syn-agent-current',
    1,
    'msg-b-claim',
    'syn-bot-a'
  );
  assert.strictEqual(authMismatch.authorized, false);
  assert.strictEqual(authMismatch.reason, 'ACCOUNT_MISMATCH');

  // Correct account Bot B -> authorized
  const authSuccess = control.authorizeReply(
    'syn-agent-current',
    1,
    'msg-b-claim',
    'syn-bot-b'
  );
  assert.strictEqual(authSuccess.authorized, true);
  assert.strictEqual(authSuccess.replyingAccountId, 'syn-bot-b');
  assert.strictEqual(control.messages.find((m) => m.id === 'msg-b-claim').status, 'replied');
});
