function addService() {
  const row = document.createElement('div');
  row.className = 'edit-row';
  row.innerHTML = '<label>Услуга<input name="service_name"></label><label>Описание<textarea name="service_text"></textarea></label><label>Цена от (€)<input name="service_price"></label><button type="button" class="remove" aria-label="Премахни услугата" title="Премахни услугата">×</button>';
  row.querySelector('button').onclick = () => row.remove();
  document.querySelector('#services-editor').append(row);
  row.querySelector('input').focus();
}
function addMember() {
  const container = document.querySelector('#team-editor');
  const row = document.createElement('div');
  row.className = 'edit-row team-edit';
  row.innerHTML = `<label>Име<input name="team_name"></label><label>Роля / квалификация<input name="team_role"></label><label>Представяне<textarea name="team_bio"></textarea></label><label>Снимка<input type="file" name="team_image_${container.children.length}" accept="image/jpeg,image/png,image/webp"></label>`;
  container.append(row);
  row.querySelector('input').focus();
}
