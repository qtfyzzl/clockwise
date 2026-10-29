
#include "Sprite.h"

boolean Sprite::collidedWith(Sprite* sprite) {
  return (this->_x < sprite->_x + sprite->_width &&
          this->_x + this->_width > sprite->_x &&
          this->_y < sprite->_y + sprite->_height &&
          this->_y + this->_height > sprite->_y);
}

void Sprite::logPosition() {
  Serial.print("x = "); Serial.print(_x); Serial.print(", y = "); Serial.print(_y); 
  Serial.print(", w = "); Serial.print(_width); Serial.print(", h = "); Serial.println(_height);
}

// Base implementation. Sprite::name() is the class' key function: without a
// definition the vtable is never emitted and every subclass fails to link
// ("undefined reference to vtable for Sprite").
const char* Sprite::name() {
  return "Sprite";
}
