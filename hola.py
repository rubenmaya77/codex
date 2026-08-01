import torch
import torch.nn as nn
import torch.optim as optim

# ==========================================
# 1. ARQUITECTURA BASE (Fases 1 y 2)
# ==========================================
class DEQCell(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.fc_z = nn.Linear(dim, dim)
        self.fc_x = nn.Linear(dim, dim)
        self.act = nn.Tanh()
        self.norm = nn.LayerNorm(dim)

    def forward(self, z, x):
        return self.norm(self.act(self.fc_z(z) + self.fc_x(x)))

class KMFractalSolver(nn.Module):
    def __init__(self, cell, max_iter=20, tol=1e-3, theta=0.5):
        super().__init__()
        self.cell = cell
        self.max_iter = max_iter
        self.tol = tol
        self.theta = theta

    def forward(self, x):
        z = torch.zeros_like(x)
        iter_count = 0
        
        for k in range(self.max_iter):
            z_next_raw = self.cell(z, x)
            z_next = (1 - self.theta) * z + self.theta * z_next_raw
            
            res = torch.norm(z_next - z) / (torch.norm(z) + 1e-5)
            z = z_next
            iter_count += 1
            
            if res < self.tol:
                break
                
        return z, iter_count # Devolvemos también las iteraciones para monitoreo

# ==========================================
# 2. EL CLASIFICADOR CON MAGIA O(1) (Fases 3 y 4)
# ==========================================
class FractalTextClassifier(nn.Module):
    def __init__(self, vocab_size, embed_dim, num_classes):
        super().__init__()
        self.embedding = nn.EmbeddingBag(vocab_size, embed_dim, sparse=False)
        self.cell = DEQCell(embed_dim)
        self.solver = KMFractalSolver(self.cell, max_iter=30, tol=1e-4, theta=0.6)
        self.classifier = nn.Linear(embed_dim, num_classes)

    def forward(self, text, offsets):
        x = self.embedding(text, offsets)
        
        # 🔴 EL TRUCO O(1): Encontrar el punto fijo SIN guardar el historial de gradientes
        with torch.no_grad():
            z_star, iters = self.solver(x)
        
        # 🟢 RECONEXIÓN: Inyectar z_star de vuelta al grafo de cálculo.
        # Desconectamos z_star del pasado, pero exigimos que calcule gradientes a partir de aquí
        z_star = z_star.detach().requires_grad_()
        
        # Damos UN SOLO PASO con la capa para registrar las operaciones en autograd
        # Como z_star es el punto de equilibrio, f(z_star) es casi igual a z_star.
        z_final = self.cell(z_star, x)
        
        # Clasificar desde este punto de equilibrio
        out = self.classifier(z_final)
        return out, iters

# ==========================================
# 3. BUCLE DE ENTRENAMIENTO (Prueba Rápida)
# ==========================================
def train_deq():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Usando dispositivo: {device}")

    # Hiperparámetros
    VOCAB_SIZE = 1000
    EMBED_DIM = 128
    NUM_CLASSES = 2
    BATCH_SIZE = 32
    
    # Modelo y optimizador
    model = FractalTextClassifier(VOCAB_SIZE, EMBED_DIM, NUM_CLASSES).to(device)
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.CrossEntropyLoss()

    # Generar datos sintéticos (Simulando 100 batches)
    print("Iniciando entrenamiento...")
    for epoch in range(5):
        epoch_loss = 0
        total_iters = 0
        
        for batch in range(100):
            # Crear datos falsos (Longitud de texto variable simulada)
            text = torch.randint(0, VOCAB_SIZE, (BATCH_SIZE * 10,)).to(device)
            offsets = torch.arange(0, BATCH_SIZE * 10, 10).to(device)
            labels = torch.randint(0, NUM_CLASSES, (BATCH_SIZE,)).to(device)

            optimizer.zero_grad()
            
            # Forward pass
            outputs, iters = model(text, offsets)
            loss = criterion(outputs, labels)
            
            # Backward pass (Solo consume O(1) de memoria sin importar las 'iters')
            loss.backward()
            
            # Gradient Clipping crítico en DEQs para evitar inestabilidad temprana
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            
            optimizer.step()
            
            epoch_loss += loss.item()
            total_iters += iters
            
        avg_loss = epoch_loss / 100
        avg_iters = total_iters / 100
        
        print(f"Época {epoch+1} | Loss: {avg_loss:.4f} | Iteraciones KM Promedio: {avg_iters:.1f}/30")

if __name__ == "__main__":
    train_deq()