---
name: test-driven-development
description: "TDD cycle (RED-GREEN-REFACTOR) with Django/Jest templates. Use before implementing any function/component when the project has a test suite. Never modify the test to make it pass — modify the code."
version: 1.0.0
license: MIT
metadata:
  tags: [tdd, testing, django, jest]
  related_skills: [writing-plans, subagent-driven-development, requesting-code-review]
---

# TDD (Test-Driven Development)

## El Ciclo

```
RED    → Escribir test que FALLE
GREEN  → Escribir código MÍNIMO para que pase
REFACTOR → Mejorar sin romper tests
```

## Flujo

### Paso 1: Escribir el Test

Escribe el test primero, cubriendo caso normal, caso borde, caso de error.

### Paso 2: Verificar que Falla

```bash
# Django
python manage.py test app.tests.test_modulo -v 2

# Jest
npm test -- --testPathPattern=Component.test
```

### Paso 3: Implementar

Escribe el código mínimo para que el test anterior pase. NO modifiques el test.

### Paso 4: Verificar que Pasa

```bash
# Django
python manage.py test app.tests.test_modulo -v 2

# Jest
npm test -- --testPathPattern=Component.test
```

### Paso 5: Refactor

Mejora legibilidad/eficiencia. Verifica que TODOS los tests sigan pasando.

## Reglas

1. **NUNCA** modificar el test para que pase — modificar el código
2. **UNA** cosa a la vez — no mezclar features
3. **SIEMPRE** verificar que tests pasan después de cada cambio
4. Si un test falla después de refactor → el refactor rompió algo

## Templates de Tests

### Django

```python
from django.test import TestCase
from .models import MiModelo

class MiModeloTest(TestCase):
    def setUp(self):
        self.objeto = MiModelo.objects.create(campo="valor")
    
    def test_campo_es_correcto(self):
        self.assertEqual(self.objeto.campo, "valor")
    
    def test_campo_vacio_lanza_error(self):
        with self.assertRaises(Exception):
            MiModelo.objects.create(campo="")
```

### React (Jest + RTL)

```jsx
import { render, screen } from '@testing-library/react';
import MiComponente from './MiComponente';

describe('MiComponente', () => {
  it('muestra el título', () => {
    render(<MiComponente titulo="Hola" />);
    expect(screen.getByText('Hola')).toBeInTheDocument();
  });

  it('ejecuta onClick al hacer click', () => {
    const handleClick = jest.fn();
    render(<MiComponente onClick={handleClick} />);
    screen.getByRole('button').click();
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
```
