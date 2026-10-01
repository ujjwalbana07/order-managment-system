if (window.matchMedia('(max-width: 768px)').matches) { document.querySelectorAll('.responsive-panel').forEach(panel => { panel.open = false; }); }
const search = document.querySelector('#account-search');
const select = document.querySelector('#account-select');
if (search && select) {
  const options = Array.from(select.options, option => option.cloneNode(true));
  search.addEventListener('input', () => {
    const selected = select.value;
    const query = search.value.trim().toLowerCase();
    select.replaceChildren(...options.filter(option => option.value === 'all' || option.value === selected || option.text.toLowerCase().includes(query)).map(option => option.cloneNode(true)));
    select.value = selected;
  });
}
const orderForm = document.querySelector('#order-form');
if (orderForm) {
  let dirty = false, timer, controller;
  orderForm.addEventListener('input', () => { dirty = true; clearTimeout(timer); timer = setTimeout(preview, 250); });
  orderForm.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  async function preview() {
    if (controller) controller.abort();
    controller = new AbortController();
    const data = new FormData(orderForm);
    orderForm.querySelectorAll('[disabled]').forEach(input => data.set(input.name, input.value));
    data.delete('image');
    try {
      const response = await fetch(orderForm.dataset.preview, {method: 'POST', body: data, signal: controller.signal});
      const result = await response.json();
      const suggested = document.querySelector('#use-sale-suggestion');
      suggested.hidden = !result.suggested_inr;
      suggested.dataset.amount = result.suggested_inr || '';
      document.querySelector('#sale-suggestion').textContent = result.suggested_inr ? `Suggested INR sale: ${result.suggested_inr}. You can enter the actual payout instead.` : '';
      document.querySelector('#cost-preview').textContent = result.error || `Net weight: ${result.net_wt} · Pure 995: ${result.pure_995_6dp} · Gold: ${result.gold_amount} · Diamond: ${result.diamond_value} · Labour: ${result.labour_amount} · Total: ${result.total_bill} · Net earnings: ${result.net_earnings}`;
    } catch (error) { if (error.name !== 'AbortError') document.querySelector('#cost-preview').textContent = 'Preview is unavailable. Check your connection and try again.'; }
  }
  document.querySelector('#use-sale-suggestion').addEventListener('click', event => {
    orderForm.elements.inr_sold.value = event.currentTarget.dataset.amount;
    orderForm.elements.inr_sold.dispatchEvent(new Event('input', {bubbles:true}));
  });
  orderForm.elements.account.addEventListener('change', async () => {
    if (orderForm.dataset.new !== 'true' || !orderForm.elements.account.value) return;
    try {
      const response = await fetch(`/orders/account-defaults/${orderForm.elements.account.value}/`);
      if (response.ok) { orderForm.elements.gold_rate.value = (await response.json()).gold_rate; preview(); }
    } catch (_) { /* Save still validates the selected account and its default. */ }
  });
  preview();
}
const paymentForm = document.querySelector('#payment-form');
if (paymentForm) {
  const components = ['Gold', 'Diamond', 'Labour'];
  function cents(value) {
    if (!/^\d+(\.\d{0,2})?$/.test(value)) return null;
    const [whole, fraction = ''] = value.split('.');
    return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  }
  function remaining() {
    const amount = cents(paymentForm.elements.amount.value);
    const parts = components.map(name => cents(paymentForm.elements[name].value));
    const valid = amount !== null && parts.every(value => value !== null);
    let text = 'Enter amounts with at most two decimal places.';
    let left;
    if (valid) { left = amount - parts.reduce((a,b) => a+b, 0n); const absolute = left < 0n ? -left : left; text = `Left to allocate: ${left < 0n ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`; }
    document.querySelector('#allocation-left').textContent = text;
    document.querySelector('#save-payment').disabled = !valid || left !== 0n || amount === 0n;
  }
  paymentForm.addEventListener('input', remaining);
  document.querySelector('#split-payment').addEventListener('click', async () => {
    try {
      const response = await fetch(paymentForm.dataset.split, {method:'POST', body: new FormData(paymentForm)});
      const values = await response.json();
      if (!response.ok) { document.querySelector('#allocation-left').textContent = values.error; return; }
      components.forEach(name => { paymentForm.elements[name].value = values[name]; }); remaining();
    } catch (_) { document.querySelector('#allocation-left').textContent = 'Could not split the payment. Try again.'; }
  });
  remaining();
}
const bulkDeleteForm = document.querySelector('#bulk-delete-form');
if (bulkDeleteForm) {
  const selectAll = bulkDeleteForm.querySelector('#select-all-orders');
  const boxes = Array.from(bulkDeleteForm.querySelectorAll('.order-select'));
  const button = bulkDeleteForm.querySelector('#bulk-delete-button');
  const count = bulkDeleteForm.querySelector('#bulk-selected-count');
  function refreshBulkDelete() {
    const selected = boxes.filter(box => box.checked).length;
    button.disabled = selected === 0;
    count.textContent = selected ? `${selected} order${selected === 1 ? '' : 's'} selected.` : 'No orders selected.';
    if (selectAll) {
      selectAll.checked = selected > 0 && selected === boxes.length;
      selectAll.indeterminate = selected > 0 && selected < boxes.length;
    }
  }
  if (selectAll) selectAll.addEventListener('change', () => { boxes.forEach(box => { box.checked = selectAll.checked; }); refreshBulkDelete(); });
  boxes.forEach(box => box.addEventListener('change', refreshBulkDelete));
  bulkDeleteForm.addEventListener('submit', event => {
    const selected = boxes.filter(box => box.checked).length;
    if (!selected || !window.confirm(`Delete ${selected} selected order${selected === 1 ? '' : 's'}?`)) event.preventDefault();
  });
  refreshBulkDelete();
}
